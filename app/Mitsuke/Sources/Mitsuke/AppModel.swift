// 앱 상태. DB를 주기적으로 다시 읽어서 파이프라인이 쌓은 매물을 반영한다.

import AppKit
import Foundation
import UserNotifications

@MainActor
final class AppModel: ObservableObject {
    @Published var listings: [Listing] = []
    @Published var searches: [Search] = []
    @Published var settings = GlobalSettings()
    @Published var lastRun: RunInfo?
    @Published var monthCostUSD = 0.0
    @Published var error: String?
    @Published var includeFiltered = false { didSet { reload() } }
    @Published var isRunning = false
    /// 알림이 꺼져 있으면 파이프라인의 알림이 조용히 실패한다. 화면에 경고를 띄우려고 확인한다
    @Published var notificationsAllowed = true
    @Published var showDisliked = false
    @Published var showLowScore = false
    /// 이 점수 미만은 기본 목록에서 숨긴다
    static let lowScore = 20
    /// 방금 👎로 숨긴 매물. 잠깐 "되돌리기" 막대를 보여준다
    @Published var justHidden: Listing?
    @Published private(set) var lastViewed: Date

    nonisolated static let root: URL = {
        if let path = Bundle.main.object(forInfoDictionaryKey: "MitsukeRoot") as? String, !path.hasPrefix("__") {
            return URL(fileURLWithPath: path)
        }
        return URL(fileURLWithPath: FileManager.default.currentDirectoryPath)
    }()
    nonisolated static let dbPath = root.appendingPathComponent("data/mitsuke.db").path
    static let launchdLabel = "com.mitsuke.run"

    private var db: Database?
    private var timer: Timer?

    init() {
        lastViewed = UserDefaults.standard.object(forKey: "lastViewed") as? Date ?? .distantPast
        reload()
        Task { await checkNotifications(askIfUndecided: true) }
        timer = Timer.scheduledTimer(withTimeInterval: 30, repeats: true) { [weak self] _ in
            Task { @MainActor in
                self?.reload()
                await self?.checkNotifications(askIfUndecided: false)
            }
        }
    }

    /// 👎한 매물과 낮은 점수 매물은 기본 목록에서 숨긴다 (각 토글을 켜면 보임)
    var visibleListings: [Listing] {
        listings.filter { l in
            (showDisliked || l.feedback != -1) && (showLowScore || !Self.isLow(l))
        }
    }

    static func isLow(_ l: Listing) -> Bool { (l.score ?? 100) < lowScore }

    /// 마지막으로 목록을 본 뒤에 들어온 통과 매물
    var unseen: [Listing] {
        listings.filter { $0.passed && $0.feedback != -1 && !Self.isLow($0) && $0.firstSeen > lastViewed }
    }

    func markViewed() {
        lastViewed = Date()
        UserDefaults.standard.set(lastViewed, forKey: "lastViewed")
    }

    private func database() throws -> Database {
        if let db { return db }
        let opened = try Database(path: Self.dbPath)
        db = opened
        return opened
    }

    func reload() {
        do {
            let db = try database()
            listings = try db.listings(includeFiltered: includeFiltered)
            searches = try db.searches()
            settings = try db.settings()
            lastRun = try db.lastRun()
            // 목록 위쪽(새 매물) 썸네일을 미리 받아 둔다. 메뉴바나 창을 열면 바로 보이게
            ImageStore.shared.prefetch(visibleListings.prefix(40).compactMap { l in l.imageURL.map { ($0, l.localThumb) } })
            monthCostUSD = try db.monthCostUSD()
            error = nil
        } catch {
            self.error = error.localizedDescription
            db = nil
        }
    }

    private func write(_ body: (Database) throws -> Void) {
        do {
            try body(try database())
            reload()
        } catch {
            self.error = error.localizedDescription
        }
    }

    // MARK: - 알림 권한

    func checkNotifications(askIfUndecided: Bool) async {
        let center = UNUserNotificationCenter.current()
        var status = await center.notificationSettings().authorizationStatus
        if status == .notDetermined && askIfUndecided {
            // 앱 화면에서 물어야 허용 창이 뜬다 (launchd에서 부른 알림 모드에서는 안 뜬다)
            _ = try? await center.requestAuthorization(options: [.alert, .sound])
            status = await center.notificationSettings().authorizationStatus
        }
        notificationsAllowed = status == .authorized || status == .provisional
    }

    func openNotificationSettings() {
        open(URL(string: "x-apple.systempreferences:com.apple.Notifications-Settings.extension?id=com.mitsuke.app"))
    }

    // MARK: - 설정 편집

    func addSearch(_ keyword: String) {
        let k = keyword.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !k.isEmpty else { return }
        if searches.contains(where: { $0.keyword == k }) {
            error = "이미 있는 검색어: \(k)"
            return
        }
        write { try $0.addSearch(keyword: k) }
    }

    func updateSearch(_ s: Search) { write { try $0.updateSearch(s) } }
    func deleteSearch(_ s: Search) { write { try $0.deleteSearch(id: s.id) } }
    func saveSettings(_ g: GlobalSettings) { write { try $0.saveSettings(g) } }

    func rateQueue() -> [Listing] {
        (try? database().rateQueue()) ?? []
    }

    func setFeedback(_ listing: Listing, _ value: Int?) {
        write { try $0.setFeedback(listingID: listing.id, value: value) }
    }

    var feedbackCount: (likes: Int, dislikes: Int) {
        (listings.filter { $0.feedback == 1 }.count, listings.filter { $0.feedback == -1 }.count)
    }

    /// 같은 버튼을 다시 누르면 피드백을 지운다
    func toggleFeedback(_ listing: Listing, _ value: Int) {
        let new = listing.feedback == value ? nil : value
        write { try $0.setFeedback(listingID: listing.id, value: new) }
        if new == -1 { announceHidden(listing) }
    }

    func announceHidden(_ listing: Listing) {
        justHidden = listing
        Task {
            try? await Task.sleep(for: .seconds(6))
            if justHidden?.id == listing.id { justHidden = nil }
        }
    }

    func undoHide() {
        guard let listing = justHidden else { return }
        setFeedback(listing, nil)
        justHidden = nil
    }

    // MARK: - 지금 확인

    /// launchd 작업을 바로 한 번 실행한다 (1시간 주기는 그대로)
    func runNow() {
        guard !isRunning else { return }
        isRunning = true
        let task = Process()
        task.executableURL = URL(fileURLWithPath: "/bin/launchctl")
        task.arguments = ["kickstart", "gui/\(getuid())/\(Self.launchdLabel)"]
        task.terminationHandler = { p in
            Task { @MainActor in
                if p.terminationStatus != 0 {
                    self.error = "자동 실행이 등록돼 있지 않습니다 (scripts/install_launchd.sh)"
                    self.isRunning = false
                    return
                }
                // 파이프라인은 검색어 사이 대기 때문에 수십 초 걸린다. 끝날 때까지 몇 번 다시 읽는다
                for _ in 0..<12 {
                    try? await Task.sleep(for: .seconds(10))
                    self.reload()
                    if let run = self.lastRun, run.finishedAt != nil, run.startedAt.timeIntervalSinceNow > -180 { break }
                }
                self.isRunning = false
            }
        }
        do { try task.run() } catch {
            self.error = error.localizedDescription
            isRunning = false
        }
    }

    func open(_ url: URL?) {
        if let url { NSWorkspace.shared.open(url) }
    }
}
