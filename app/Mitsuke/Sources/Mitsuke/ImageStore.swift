// 사진 캐시. 순서: 메모리 → 파이썬이 채점할 때 받아 둔 로컬 파일(data/images) → 인터넷.
// AsyncImage는 캐시가 없어서 스크롤하거나 창을 다시 열 때마다 새로 받았다.

import AppKit
import SwiftUI

@MainActor
final class ImageStore {
    static let shared = ImageStore()

    private let memory = NSCache<NSURL, NSImage>()
    // 백그라운드 작업은 Data만 넘긴다 (NSImage는 스레드 사이로 넘기면 안 된다)
    private var inFlight: [URL: Task<Data?, Never>] = [:]
    private let session: URLSession = {
        let config = URLSessionConfiguration.default
        config.urlCache = URLCache(memoryCapacity: 50_000_000, diskCapacity: 300_000_000)
        config.requestCachePolicy = .returnCacheDataElseLoad  // 매물 사진은 바뀌지 않는다
        return URLSession(configuration: config)
    }()

    private init() { memory.countLimit = 600 }

    func cached(_ url: URL) -> NSImage? { memory.object(forKey: url as NSURL) }

    func load(_ url: URL, localFile: URL? = nil) async -> NSImage? {
        if let hit = cached(url) { return hit }
        let task: Task<Data?, Never>
        if let running = inFlight[url] {
            task = running  // 같은 사진을 동시에 두 번 받지 않는다
        } else {
            let session = self.session
            task = Task.detached(priority: .userInitiated) {
                if let localFile, let data = try? Data(contentsOf: localFile) { return data }
                return try? await session.data(from: url).0
            }
            inFlight[url] = task
        }
        let data = await task.value
        inFlight[url] = nil
        if let hit = cached(url) { return hit }
        guard let data, let image = NSImage(data: data) else { return nil }
        memory.setObject(image, forKey: url as NSURL)
        return image
    }

    /// 곧 보일 사진을 미리 받아 둔다
    func prefetch(_ items: [(URL, URL?)]) {
        for (url, local) in items where cached(url) == nil && inFlight[url] == nil {
            Task { _ = await load(url, localFile: local) }
        }
    }
}

extension Listing {
    private var cacheKey: String { id.replacingOccurrences(of: ":", with: "_") }
    var localThumb: URL { AppModel.root.appendingPathComponent("data/images/\(cacheKey)_thumb.webp") }
    var localFull: URL { AppModel.root.appendingPathComponent("data/images/\(cacheKey)_full.jpg") }
}

/// 캐시를 쓰는 이미지 뷰
struct CachedImage: View {
    let url: URL?
    var localFile: URL?
    var fill = true
    @State private var image: NSImage?

    var body: some View {
        Group {
            if let image {
                if fill {
                    Image(nsImage: image).resizable().scaledToFill()
                } else {
                    Image(nsImage: image).resizable().scaledToFit()
                }
            } else {
                Rectangle().fill(.quaternary)
            }
        }
        .task(id: url) {
            guard let url else { return }
            image = ImageStore.shared.cached(url)  // 메모리에 있으면 깜빡임 없이 바로
            if image == nil { image = await ImageStore.shared.load(url, localFile: localFile) }
        }
    }
}
