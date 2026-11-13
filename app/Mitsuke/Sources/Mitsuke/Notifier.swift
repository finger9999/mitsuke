// 알림. 파이썬이 `Mitsuke --notify --title ... --open URL`로 부르면 알림만 올리고 끝난다.
// 사용자가 알림을 누르면 macOS가 메뉴바에 떠 있는 앱(또는 새로 띄운 앱)에 전달하고, 여기서 URL을 연다.

import AppKit
import UserNotifications

enum NotifyCommand {
    static func parseArgs() -> [String: String] {
        var result: [String: String] = [:]
        var it = CommandLine.arguments.dropFirst().makeIterator()
        while let key = it.next() {
            guard key.hasPrefix("--") else { continue }
            let name = String(key.dropFirst(2))
            if name == "notify" { result[name] = "1"; continue }
            if let value = it.next() { result[name] = value }
        }
        return result
    }

    /// 원격 이미지를 받아 PNG로 저장한다. 메루카리 썸네일은 webp라서 알림 첨부용으로 변환한다.
    static func downloadImage(_ urlString: String) -> URL? {
        guard let url = URL(string: urlString),
              let data = try? Data(contentsOf: url),
              let image = NSImage(data: data),
              let tiff = image.tiffRepresentation,
              let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:])
        else { return nil }
        let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".png")
        return (try? png.write(to: file)) != nil ? file : nil
    }

    /// 알림을 올리고 프로세스를 끝낸다. 돌아오지 않는다.
    static func run(_ args: [String: String]) -> Never {
        // 예전 알림 도우미와 같은 조건(NSApplication 위)에서 돌린다. 화면에는 아무것도 안 뜬다
        let app = NSApplication.shared
        app.setActivationPolicy(.prohibited)
        DispatchQueue.main.async { post(args) }
        app.run()
        exit(0)
    }

    private static func post(_ args: [String: String]) {
        let center = UNUserNotificationCenter.current()
        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            guard granted else {
                fputs("알림 권한 없음: \(error?.localizedDescription ?? "거부됨")\n", stderr)
                exit(2)
            }
            let content = UNMutableNotificationContent()
            content.title = args["title"] ?? "미츠케"
            content.subtitle = args["subtitle"] ?? ""
            content.body = args["message"] ?? ""
            content.sound = .default
            if let open = args["open"] { content.userInfo = ["url": open] }
            if let group = args["group"] { content.threadIdentifier = group }
            if let image = args["image"], let file = downloadImage(image),
               let attachment = try? UNNotificationAttachment(identifier: "image", url: file) {
                content.attachments = [attachment]
            }
            let request = UNNotificationRequest(
                identifier: args["group"] ?? UUID().uuidString, content: content, trigger: nil)
            center.add(request) { error in
                if let error {
                    fputs("알림 실패: \(error.localizedDescription)\n", stderr)
                    exit(1)
                }
                exit(0)
            }
        }
    }
}

/// 앱 모드에서 알림 클릭을 받는다
final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    func applicationDidFinishLaunching(_ notification: Notification) {
        UNUserNotificationCenter.current().delegate = self
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        if let s = response.notification.request.content.userInfo["url"] as? String, let url = URL(string: s) {
            NSWorkspace.shared.open(url)
        }
        done()
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }
}
