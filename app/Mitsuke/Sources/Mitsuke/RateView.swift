// 빠른 평가: 사진을 크게 하나씩 보면서 👍👎만 누른다. ← 👎 / → 👍 / 스페이스 건너뛰기.
// 모인 평가는 채점할 때 비교 사진으로 쓰이고, 나중에 평가셋(정답)이 된다.

import SwiftUI

struct RateView: View {
    @EnvironmentObject var model: AppModel
    @State private var queue: [Listing] = []
    @State private var index = 0
    @State private var ratedNow = 0
    /// 되돌리기용: 이번에 평가한 순서 (대기열 위치, 매물)
    @State private var history: [(index: Int, listing: Listing)] = []

    private var current: Listing? { index < queue.count ? queue[index] : nil }

    var body: some View {
        VStack(spacing: 0) {
            header
            Divider()
            if let item = current {
                card(item)
            } else {
                ContentUnavailableView {
                    Label("다 평가했어요", systemImage: "checkmark.circle")
                } description: {
                    Text("이번에 \(ratedNow)개 평가했어요. 새 매물이 쌓이면 다시 열어 주세요.")
                } actions: {
                    Button("새로 불러오기", action: reload)
                }
            }
        }
        .frame(minWidth: 520, minHeight: 640)
        .onAppear(perform: reload)
        .focusable()
        .focusEffectDisabled()
        .onKeyPress(.leftArrow) { rate(-1); return .handled }
        .onKeyPress(.rightArrow) { rate(1); return .handled }
        .onKeyPress(.space) { skip(); return .handled }
    }

    private var header: some View {
        let counts = model.feedbackCount
        return HStack {
            Text("👍 \(counts.likes) · 👎 \(counts.dislikes)").font(.callout)
            Spacer()
            Button("되돌리기 (⌘Z)", action: undo).disabled(history.isEmpty).keyboardShortcut("z")
            Text(current == nil ? "" : "\(index + 1) / \(queue.count)").foregroundStyle(.secondary)
        }
        .padding(12)
    }

    private func card(_ item: Listing) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            AsyncImage(url: item.fullImageURL) { phase in
                switch phase {
                case .success(let image): image.resizable().scaledToFit()
                case .failure: Thumbnail(url: item.imageURL).scaledToFit()
                default: ProgressView().frame(maxWidth: .infinity, maxHeight: .infinity)
                }
            }
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(.quaternary.opacity(0.3), in: .rect(cornerRadius: 8))
            .onTapGesture { model.open(item.url) }
            .help("클릭하면 메루카리에서 사진 전체 보기")

            HStack {
                Text(Fmt.yen(item.priceJPY)).font(.title2.weight(.semibold))
                if let score = item.score { ScoreBadge(score: score) }
                if item.status == "filtered" { Text("규칙 탈락").font(.caption).foregroundStyle(.orange) }
                Spacer()
                Text(item.search).font(.caption).foregroundStyle(.secondary)
            }
            Text(item.title).font(.callout).lineLimit(2)
            if let reason = item.filterReason ?? item.scoreReason {
                Text("AI: \(reason)").font(.caption).foregroundStyle(.secondary).lineLimit(3)
            }

            HStack(spacing: 12) {
                Button { rate(-1) } label: {
                    Label("별로 (←)", systemImage: "hand.thumbsdown").frame(maxWidth: .infinity)
                }
                .tint(.red)
                Button { skip() } label: {
                    Text("모르겠음 (스페이스)").frame(maxWidth: .infinity)
                }
                Button { rate(1) } label: {
                    Label("좋아 (→)", systemImage: "hand.thumbsup").frame(maxWidth: .infinity)
                }
                .tint(.green)
            }
            .controlSize(.large)
            .buttonStyle(.borderedProminent)
        }
        .padding(16)
    }

    private func reload() {
        queue = model.rateQueue()
        index = 0
    }

    private func rate(_ value: Int) {
        guard let item = current else { return }
        model.setFeedback(item, value)
        history.append((index, item))
        ratedNow += 1
        index += 1
    }

    /// 방금 누른 평가를 지우고 그 매물로 돌아간다
    private func undo() {
        guard let last = history.popLast() else { return }
        model.setFeedback(last.listing, nil)
        ratedNow -= 1
        index = last.index
    }

    private func skip() {
        guard current != nil else { return }
        index += 1
    }
}
