import SwiftUI

struct MitsukeApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var appDelegate
    @StateObject private var model = AppModel()

    var body: some Scene {
        // 맨 앞에 둔 창이 실행할 때 열린다. Dock 아이콘을 눌러도 다시 열린다
        Window("미츠케", id: "listings") {
            ListingsView().environmentObject(model)
        }
        .defaultSize(width: 980, height: 720)

        MenuBarExtra {
            MenuBarView().environmentObject(model)
        } label: {
            // 새 매물이 있으면 개수를 같이 보여준다
            let count = model.unseen.count
            Text(count > 0 ? "見 \(count)" : "見")
        }
        .menuBarExtraStyle(.window)

        Window("빠른 평가", id: "rate") {
            RateView().environmentObject(model)
        }
        .defaultSize(width: 620, height: 760)

        Window("미츠케 설정", id: "settings") {
            SettingsView().environmentObject(model)
        }
        .defaultSize(width: 580, height: 720)
        .windowResizability(.contentSize)
    }
}

/// 메뉴바에서 창을 열 때 다른 앱 뒤에 숨지 않게 앞으로 끌어온다
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
