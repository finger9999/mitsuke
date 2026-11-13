// 미츠케 알림 도우미.
//   MitsukeNotifier --title T --subtitle S --message M [--open URL] [--image URL] [--group ID]
// 알림을 올리고 바로 끝난다. 사용자가 알림을 누르면 macOS가 이 앱을 다시 띄우고,
// 그때 delegate가 --open으로 받은 URL을 연다.

import AppKit
import UserNotifications

func parseArgs() -> [String: String] {
    var result: [String: String] = [:]
    var it = CommandLine.arguments.dropFirst().makeIterator()
    while let key = it.next() {
        guard key.hasPrefix("--"), let value = it.next() else { continue }
        result[String(key.dropFirst(2))] = value
    }
    return result
}

/// 원격 이미지를 받아 PNG로 저장한다. 메루카리 썸네일은 webp라서 알림 첨부용으로 변환이 필요하다.
func downloadImage(_ urlString: String) -> URL? {
    guard let url = URL(string: urlString),
          let data = try? Data(contentsOf: url),
          let image = NSImage(data: data),
          let tiff = image.tiffRepresentation,
          let png = NSBitmapImageRep(data: tiff)?.representation(using: .png, properties: [:])
    else { return nil }
    let file = FileManager.default.temporaryDirectory.appendingPathComponent(UUID().uuidString + ".png")
    return (try? png.write(to: file)) != nil ? file : nil
}

final class AppDelegate: NSObject, NSApplicationDelegate, UNUserNotificationCenterDelegate {
    let args = parseArgs()

    func applicationDidFinishLaunching(_ notification: Notification) {
        let center = UNUserNotificationCenter.current()
        center.delegate = self

        guard let title = args["title"] else {
            // 알림 클릭으로 실행된 경우. 응답을 받을 시간을 주고 끝낸다
            DispatchQueue.main.asyncAfter(deadline: .now() + 10) { NSApp.terminate(nil) }
            return
        }

        center.requestAuthorization(options: [.alert, .sound]) { granted, error in
            guard granted else {
                fputs("알림 권한 없음: \(error?.localizedDescription ?? "거부됨")\n", stderr)
                exit(2)
            }
            let content = UNMutableNotificationContent()
            content.title = title
            content.subtitle = self.args["subtitle"] ?? ""
            content.body = self.args["message"] ?? ""
            content.sound = .default
            if let open = self.args["open"] { content.userInfo = ["url": open] }
            if let group = self.args["group"] { content.threadIdentifier = group }
            if let image = self.args["image"], let file = downloadImage(image),
               let attachment = try? UNNotificationAttachment(identifier: "image", url: file) {
                content.attachments = [attachment]
            }
            let request = UNNotificationRequest(
                identifier: self.args["group"] ?? UUID().uuidString, content: content, trigger: nil)
            center.add(request) { error in
                if let error {
                    fputs("알림 실패: \(error.localizedDescription)\n", stderr)
                    exit(1)
                }
                exit(0)
            }
        }
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, didReceive response: UNNotificationResponse,
                                withCompletionHandler done: @escaping () -> Void) {
        if let s = response.notification.request.content.userInfo["url"] as? String, let url = URL(string: s) {
            NSWorkspace.shared.open(url)
        }
        done()
        NSApp.terminate(nil)
    }

    func userNotificationCenter(_ center: UNUserNotificationCenter, willPresent notification: UNNotification,
                                withCompletionHandler done: @escaping (UNNotificationPresentationOptions) -> Void) {
        done([.banner, .sound])
    }
}

let app = NSApplication.shared
let delegate = AppDelegate()
app.delegate = delegate
app.setActivationPolicy(.accessory)
app.run()
