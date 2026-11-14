// 메뉴바 아이콘을 누르면 뜨는 작은 창. 최근 통과 매물과 바로가기.

import SwiftUI

struct MenuBarView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.openWindow) private var openWindow

    private var recent: [Listing] { Array(model.listings.filter(\.passed).prefix(8)) }

    var body: some View {
        VStack(alignment: .leading, spacing: 0) {
            header
            Divider()
            if let error = model.error {
                Text(error).font(.caption).foregroundStyle(.red).padding(12)
                Divider()
            }
            if recent.isEmpty {
                Text("아직 통과한 매물이 없어요.\n새 매물이 올라오면 여기에 쌓여요.")
                    .font(.callout).foregroundStyle(.secondary)
                    .frame(maxWidth: .infinity).padding(.vertical, 28)
            } else {
                ScrollView {
                    VStack(spacing: 0) {
                        ForEach(recent) { listing in
                            ListingRow(listing: listing, isNew: listing.firstSeen > model.lastViewed)
                            Divider().padding(.leading, 64)
                        }
                    }
                }
                .frame(maxHeight: 440)
            }
            Divider()
            footer
        }
        .frame(width: 360)
        .onAppear { model.reload() }
        .onDisappear { model.markViewed() }
    }

    private var header: some View {
        HStack {
            VStack(alignment: .leading, spacing: 2) {
                Text("미츠케").font(.headline)
                Text(lastRunText).font(.caption).foregroundStyle(.secondary)
            }
            Spacer()
            Button {
                model.runNow()
            } label: {
                if model.isRunning {
                    ProgressView().controlSize(.small)
                } else {
                    Label("지금 확인", systemImage: "arrow.clockwise")
                }
            }
            .disabled(model.isRunning)
        }
        .padding(12)
    }

    private var lastRunText: String {
        guard let run = model.lastRun else { return "아직 실행 기록 없음" }
        guard let finished = run.finishedAt else { return "확인 중…" }
        var text = "마지막 확인 \(Fmt.ago(finished)) · 새 매물 \(run.new)개 · 이번 달 $\(String(format: "%.2f", model.monthCostUSD))"
        if !run.errors.isEmpty { text += " · 오류 \(run.errors.count)" }
        return text
    }

    private var footer: some View {
        HStack {
            Button("전체 보기") {
                openWindow(id: "listings")
                bringToFront()
            }
            Button("빠른 평가") {
                openWindow(id: "rate")
                bringToFront()
            }
            Button("설정") {
                openWindow(id: "settings")
                bringToFront()
            }
            Spacer()
            Button("종료") { NSApp.terminate(nil) }
        }
        .buttonStyle(.borderless)
        .padding(12)
    }
}

struct ListingRow: View {
    @EnvironmentObject var model: AppModel
    let listing: Listing
    var isNew = false

    var body: some View {
        Button {
            model.open(listing.purchaseURL)
        } label: {
            HStack(spacing: 10) {
                Thumbnail(url: listing.imageURL).frame(width: 44, height: 44)
                VStack(alignment: .leading, spacing: 2) {
                    HStack(spacing: 6) {
                        Text(Fmt.yen(listing.priceJPY)).font(.callout.weight(.semibold))
                        if let score = listing.score { ScoreBadge(score: score) }
                        if isNew {
                            Text("NEW").font(.caption2.weight(.bold)).foregroundStyle(.white)
                                .padding(.horizontal, 4).background(.red, in: .rect(cornerRadius: 3))
                        }
                    }
                    Text(listing.scoreReason ?? listing.title).font(.caption).lineLimit(2)
                    Text("\(listing.search) · \(Fmt.ago(listing.firstSeen))")
                        .font(.caption2).foregroundStyle(.secondary)
                }
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 12).padding(.vertical, 8)
            .contentShape(Rectangle())
        }
        .buttonStyle(.plain)
        .help("Buyee에서 열기")
    }
}

struct Thumbnail: View {
    let url: URL?

    var body: some View {
        AsyncImage(url: url) { phase in
            switch phase {
            case .success(let image): image.resizable().scaledToFill()
            default: Rectangle().fill(.quaternary)
            }
        }
        .clipShape(.rect(cornerRadius: 6))
    }
}

struct ScoreBadge: View {
    let score: Int

    var body: some View {
        Text("\(score)점").font(.caption2.weight(.bold)).foregroundStyle(.white)
            .padding(.horizontal, 5).padding(.vertical, 1)
            .background(color, in: .rect(cornerRadius: 4))
    }

    private var color: Color { score >= 90 ? .green : score >= 60 ? .blue : .gray }
}

/// 👍👎 버튼. 기록은 평가셋과 채점 프롬프트 예시로 쓰인다
struct FeedbackButtons: View {
    @EnvironmentObject var model: AppModel
    let listing: Listing

    var body: some View {
        HStack(spacing: 2) {
            button("hand.thumbsup", 1, .green)
            button("hand.thumbsdown", -1, .red)
        }
    }

    private func button(_ icon: String, _ value: Int, _ color: Color) -> some View {
        let on = listing.feedback == value
        return Button {
            model.toggleFeedback(listing, value)
        } label: {
            Image(systemName: on ? icon + ".fill" : icon).foregroundStyle(on ? color : .secondary)
        }
        .buttonStyle(.borderless)
        .help(value > 0 ? "좋아요 (다시 누르면 취소)" : "별로예요 (다시 누르면 취소)")
    }
}
