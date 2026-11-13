import SwiftUI

struct MitsukeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        MenuBarExtra {
            MenuBarView().environmentObject(model)
        } label: {
            // 새 매물이 있으면 개수를 같이 보여준다
            let count = model.unseen.count
            Text(count > 0 ? "見 \(count)" : "見")
        }
        .menuBarExtraStyle(.window)

        Window("미츠케", id: "listings") {
            ListingsView().environmentObject(model)
        }
        .defaultSize(width: 980, height: 720)

        Window("미츠케 설정", id: "settings") {
            SettingsView().environmentObject(model)
        }
        .defaultSize(width: 560, height: 560)
        .windowResizability(.contentSize)
    }
}

/// 메뉴바 앱은 독 아이콘이 없어서, 창을 열 때 앞으로 끌어와야 보인다
@MainActor
func bringToFront() {
    NSApp.activate(ignoringOtherApps: true)
}

enum Fmt {
    static func yen(_ v: Int) -> String {
        "¥" + v.formatted(.number.grouping(.automatic))
    }

    static func ago(_ date: Date) -> String {
        let f = RelativeDateTimeFormatter()
        f.locale = Locale(identifier: "ko_KR")
        f.unitsStyle = .short
        return f.localizedString(for: date, relativeTo: Date())
    }
}
