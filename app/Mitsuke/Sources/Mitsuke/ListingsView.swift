// 전체 매물 창. 사진 그리드로 보고, 검색어·상태로 거른다.

import SwiftUI

struct ListingsView: View {
    @EnvironmentObject var model: AppModel
    @Environment(\.openWindow) private var openWindow
    @State private var searchFilter = "전체"
    @State private var query = ""
    @AppStorage("sortByScore") private var sortByScore = false

    private var filtered: [Listing] {
        let items = model.listings.filter { l in
            (searchFilter == "전체" || l.search == searchFilter)
                && (query.isEmpty || l.title.localizedCaseInsensitiveContains(query))
        }
        // 점수순: 점수 없는 매물은 뒤로, 같은 점수면 최신순
        return sortByScore ? items.sorted { ($0.score ?? -1, $0.firstSeen) > ($1.score ?? -1, $1.firstSeen) } : items
    }

    private var searchNames: [String] {
        ["전체"] + model.searches.map(\.keyword)
    }

    var body: some View {
        VStack(spacing: 0) {
            toolbar
            Divider()
            if let error = model.error {
                Text(error).foregroundStyle(.red).padding()
            }
            if filtered.isEmpty {
                ContentUnavailableView("매물 없음", systemImage: "tray",
                                       description: Text(model.includeFiltered ? "조건에 맞는 매물이 없어요." : "통과한 매물이 아직 없어요. '탈락·기준점 포함'을 켜면 전부 볼 수 있어요."))
            } else {
                ScrollView {
                    LazyVGrid(columns: [GridItem(.adaptive(minimum: 170, maximum: 220), spacing: 14)], spacing: 14) {
                        ForEach(filtered) { ListingCard(listing: $0) }
                    }
                    .padding(16)
                }
            }
        }
        .frame(minWidth: 560, minHeight: 400)
        .onAppear {
            model.reload()
            model.markViewed()
        }
    }

    private var toolbar: some View {
        HStack(spacing: 12) {
            Picker("검색어", selection: $searchFilter) {
                ForEach(searchNames, id: \.self) { Text($0).tag($0) }
            }
            .frame(width: 200)
            TextField("제목 검색", text: $query).textFieldStyle(.roundedBorder).frame(maxWidth: 220)
            Picker("정렬", selection: $sortByScore) {
                Text("최신순").tag(false)
                Text("점수순").tag(true)
            }
            .pickerStyle(.segmented).labelsHidden().frame(width: 130)
            Toggle("탈락·기준점 포함", isOn: $model.includeFiltered)
            Spacer()
            Text("\(filtered.count)개").foregroundStyle(.secondary)
            Button {
                openWindow(id: "rate")
            } label: {
                Label("빠른 평가", systemImage: "hand.thumbsup")
            }
            Button {
                model.runNow()
            } label: {
                Label(model.isRunning ? "확인 중…" : "지금 확인", systemImage: "arrow.clockwise")
            }
            .disabled(model.isRunning)
        }
        .padding(12)
    }
}

struct ListingCard: View {
    @EnvironmentObject var model: AppModel
    let listing: Listing

    var body: some View {
        VStack(alignment: .leading, spacing: 6) {
            Thumbnail(url: listing.imageURL)
                .aspectRatio(1, contentMode: .fit)
                .overlay(alignment: .topLeading) { badge.padding(6) }
                .opacity(listing.passed ? 1 : 0.55)
            HStack {
                Text(Fmt.yen(listing.priceJPY)).font(.headline)
                if let score = listing.score { ScoreBadge(score: score) }
                Spacer()
                FeedbackButtons(listing: listing)
            }
            Text(listing.title).font(.caption).lineLimit(2).frame(height: 30, alignment: .top)
            Text("\(listing.search) · \(Fmt.ago(listing.firstSeen))").font(.caption2).foregroundStyle(.secondary)
            if let reason = listing.filterReason {
                Text(reason).font(.caption2).foregroundStyle(.orange).lineLimit(1)
            } else if let reason = listing.scoreReason {
                Text(reason).font(.caption2).foregroundStyle(.secondary).lineLimit(2).help(reason)
            }
        }
        .contentShape(Rectangle())
        .onTapGesture { model.open(listing.purchaseURL) }
        .contextMenu {
            Button("Buyee에서 열기") { model.open(listing.purchaseURL) }
            Button("메루카리에서 열기") { model.open(listing.url) }
        }
        .help("클릭하면 Buyee에서 열기")
    }

    @ViewBuilder private var badge: some View {
        if listing.firstSeen > model.lastViewed && listing.passed {
            tag("NEW", .red)
        } else if listing.status == "filtered" {
            tag("탈락", .gray)
        } else if listing.status == "seeded" {
            tag("기준점", .gray)
        }
    }

    private func tag(_ text: String, _ color: Color) -> some View {
        Text(text).font(.caption2.weight(.bold)).foregroundStyle(.white)
            .padding(.horizontal, 5).padding(.vertical, 2)
            .background(color, in: .rect(cornerRadius: 4))
    }
}
