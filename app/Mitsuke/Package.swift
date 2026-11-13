// swift-tools-version:5.10
// Xcode에서 이 파일을 열면 프로젝트처럼 편집할 수 있다. 빌드·번들링은 scripts/build_app.sh.
import PackageDescription

let package = Package(
    name: "Mitsuke",
    platforms: [.macOS(.v14)],
    targets: [
        .executableTarget(
            name: "Mitsuke",
            path: "Sources/Mitsuke",
            linkerSettings: [.linkedLibrary("sqlite3")]
        ),
    ]
)
