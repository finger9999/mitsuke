// 설정 창. 검색어와 예산을 편집하면 DB에 저장되고, 다음 실행부터 파이프라인이 읽는다.

import SwiftUI

struct SettingsView: View {
    @EnvironmentObject var model: AppModel
    @State private var global = GlobalSettings()
    @State private var excludeText = ""
    @State private var drafts: [Search] = []
    @State private var newKeyword = ""
    @State private var saved = false

    private var dirty: Bool {
        global != model.settings || drafts != model.searches
            || excludeText != model.settings.excludeKeywords.joined(separator: ", ")
    }

    var body: some View {
        Form {
            Section {
                TextEditor(text: $global.taste)
                    .font(.body).frame(minHeight: 90)
            } header: {
                Text("취향 기준")
            } footer: {
                Text("AI가 이 내용을 보고 매물에 0~100점을 매겨요. 90점 이상만 알림이 와요. \"무조건\"이라고 쓴 조건은 확인될 때만 90점 이상을 줘요.")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section {
                YenField(label: "기본 예산", value: $global.priceMax, placeholder: "제한 없음")
                YenField(label: "아우터 예산", value: $global.outerPriceMax, placeholder: "기본 예산과 같음")
                TextField("제외 키워드", text: $excludeText, prompt: Text("쉼표로 구분 (예: パジャマ, ジャンク)"))
            } header: {
                Text("모든 검색어 공통")
            } footer: {
                Text("아우터 = 메루카리 レディース/メンズ > ジャケット/アウター 카테고리 전체")
                    .font(.caption).foregroundStyle(.secondary)
            }

            Section {
                ForEach($drafts) { $search in
                    SearchRow(search: $search) {
                        model.deleteSearch(search)
                        drafts.removeAll { $0.id == search.id }
                    }
                }
                HStack {
                    TextField("새 검색어", text: $newKeyword, prompt: Text("메루카리에서 쓰는 표기 (예: ツモリチサト)"))
                        .onSubmit(add)
                    Button("추가", action: add).disabled(newKeyword.trimmingCharacters(in: .whitespaces).isEmpty)
                }
            } header: {
                Text("검색어")
            } footer: {
                Text("새 검색어는 첫 실행 때 이미 올라와 있던 매물을 기준점으로만 저장하고, 그다음 실행부터 알림이 와요. 예산 칸을 비우면 공통 예산을 따라요.")
                    .font(.caption).foregroundStyle(.secondary)
            }
        }
        .formStyle(.grouped)
        .safeAreaInset(edge: .bottom) {
            HStack {
                if let error = model.error { Text(error).font(.caption).foregroundStyle(.red) }
                if saved && !dirty { Text("저장됨").font(.caption).foregroundStyle(.secondary) }
                Spacer()
                Button("되돌리기", action: load).disabled(!dirty)
                Button("저장", action: save).keyboardShortcut("s").buttonStyle(.borderedProminent).disabled(!dirty)
            }
            .padding(12)
            .background(.bar)
        }
        .frame(minWidth: 520, minHeight: 480)
        .onAppear {
            model.reload()
            load()
        }
    }

    private func load() {
        global = model.settings
        excludeText = model.settings.excludeKeywords.joined(separator: ", ")
        drafts = model.searches
    }

    private func add() {
        if dirty { save() }  // 편집 중이던 내용이 reload로 사라지지 않게 먼저 저장
        model.addSearch(newKeyword)
        newKeyword = ""
        load()
    }

    private func save() {
        global.excludeKeywords = splitKeywords(excludeText)
        model.saveSettings(global)
        for draft in drafts where model.searches.first(where: { $0.id == draft.id }) != draft {
            model.updateSearch(draft)
        }
        load()
        saved = true
    }
}

func splitKeywords(_ text: String) -> [String] {
    text.split(whereSeparator: { $0 == "," || $0 == "、" || $0 == "\n" })
        .map { $0.trimmingCharacters(in: .whitespaces) }
        .filter { !$0.isEmpty }
}

struct SearchRow: View {
    @Binding var search: Search
    let onDelete: () -> Void
    @State private var expanded = false
    @State private var confirmDelete = false

    var body: some View {
        DisclosureGroup(isExpanded: $expanded) {
            YenField(label: "기본 예산", value: $search.priceMax, placeholder: "공통 예산")
            YenField(label: "아우터 예산", value: $search.outerPriceMax, placeholder: "공통 예산")
            TextField("추가 제외 키워드", text: Binding(
                get: { search.excludeKeywords.joined(separator: ", ") },
                set: { search.excludeKeywords = splitKeywords($0) }
            ), prompt: Text("쉼표로 구분"))
            HStack {
                Spacer()
                if confirmDelete {
                    Text("이 검색어를 지울까요? 쌓인 매물은 남아요.").font(.caption)
                    Button("취소") { confirmDelete = false }
                    Button("삭제", role: .destructive, action: onDelete)
                } else {
                    Button("검색어 삭제", role: .destructive) { confirmDelete = true }
                }
            }
        } label: {
            HStack {
                Toggle("", isOn: $search.enabled).labelsHidden().toggleStyle(.switch).controlSize(.small)
                TextField("", text: $search.keyword).textFieldStyle(.plain)
                    .foregroundStyle(search.enabled ? .primary : .secondary)
                Spacer()
                Text(summary).font(.caption).foregroundStyle(.secondary)
            }
        }
    }

    private var summary: String {
        var parts: [String] = []
        if let p = search.priceMax { parts.append("기본 \(Fmt.yen(p))") }
        if let p = search.outerPriceMax { parts.append("아우터 \(Fmt.yen(p))") }
        if !search.excludeKeywords.isEmpty { parts.append("제외 \(search.excludeKeywords.count)") }
        return parts.isEmpty ? "공통 설정" : parts.joined(separator: " · ")
    }
}

/// 엔 금액 입력. 비우면 nil
struct YenField: View {
    let label: String
    @Binding var value: Int?
    let placeholder: String

    var body: some View {
        LabeledContent(label) {
            HStack(spacing: 4) {
                Text("¥").foregroundStyle(.secondary)
                TextField("", text: Binding(
                    get: { value.map(String.init) ?? "" },
                    set: { value = Int($0.filter(\.isNumber)) }
                ), prompt: Text(placeholder))
                .multilineTextAlignment(.trailing)
                .frame(width: 140)
            }
        }
    }
}
