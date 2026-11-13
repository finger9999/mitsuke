// 진입점. `--notify`가 있으면 알림만 보내고 끝나고, 없으면 메뉴바 앱으로 뜬다.

import SwiftUI

let args = NotifyCommand.parseArgs()
if args["notify"] != nil {
    NotifyCommand.run(args)
}

MitsukeApp.main()
