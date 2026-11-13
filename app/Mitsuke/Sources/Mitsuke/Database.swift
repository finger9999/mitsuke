// SQLite 접근. 파이썬 파이프라인과 같은 data/mitsuke.db를 쓴다.
// 앱은 매물을 읽기만 하고, 검색어(searches)와 설정(settings)만 쓴다.

import Foundation
import SQLite3

struct Listing: Identifiable, Hashable {
    let id: String
    let search: String
    let title: String
    let priceJPY: Int
    let imageURL: URL?
    let url: URL?
    let buyeeURL: URL?
    let firstSeen: Date
    let status: String
    let filterReason: String?
    let score: Int?
    let scoreReason: String?
    var feedback: Int?  // 1 = 👍, -1 = 👎

    var passed: Bool { status == "passed" || status == "notified" || status == "scored" }
    var mercariID: String { String(id.split(separator: ":").last ?? "") }
    /// 기준점·탈락 매물은 buyee_url이 비어 있어서 여기서 만든다
    var purchaseURL: URL? { buyeeURL ?? URL(string: "https://buyee.jp/mercari/item/\(mercariID)") }
}

struct Search: Identifiable, Hashable {
    var id: Int64
    var keyword: String
    var enabled: Bool
    var priceMax: Int?
    var outerPriceMax: Int?
    var excludeKeywords: [String]
}

struct GlobalSettings: Equatable {
    var taste = ""
    var priceMax: Int?
    var outerPriceMax: Int?
    var excludeKeywords: [String] = []
    var excludeCategories: [Int] = []
}

struct RunInfo {
    let startedAt: Date
    let finishedAt: Date?
    let new: Int
    let notified: Int
    let costUSD: Double
    let errors: [String]
}

enum DBError: Error, LocalizedError {
    case open(String), query(String)
    var errorDescription: String? {
        switch self {
        case .open(let m): "DB를 열 수 없음: \(m)"
        case .query(let m): "DB 오류: \(m)"
        }
    }
}

private let SQLITE_TRANSIENT = unsafeBitCast(-1, to: sqlite3_destructor_type.self)

final class Database {
    private var db: OpaquePointer?

    init(path: String) throws {
        guard sqlite3_open_v2(path, &db, SQLITE_OPEN_READWRITE, nil) == SQLITE_OK else {
            let msg = String(cString: sqlite3_errmsg(db))
            sqlite3_close(db)
            throw DBError.open("\(path) (\(msg)). 파이프라인을 한 번 실행하면 만들어집니다.")
        }
        sqlite3_busy_timeout(db, 3000)
    }

    deinit { sqlite3_close(db) }

    // MARK: - 저수준

    private enum Value { case int(Int?), text(String?) }

    private func run(_ sql: String, _ params: [Value] = [], row: ((OpaquePointer) -> Void)? = nil) throws {
        var stmt: OpaquePointer?
        guard sqlite3_prepare_v2(db, sql, -1, &stmt, nil) == SQLITE_OK else {
            throw DBError.query(String(cString: sqlite3_errmsg(db)))
        }
        defer { sqlite3_finalize(stmt) }
        for (i, p) in params.enumerated() {
            let idx = Int32(i + 1)
            switch p {
            case .int(let v?): sqlite3_bind_int64(stmt, idx, Int64(v))
            case .text(let v?): sqlite3_bind_text(stmt, idx, v, -1, SQLITE_TRANSIENT)
            default: sqlite3_bind_null(stmt, idx)
            }
        }
        while true {
            let rc = sqlite3_step(stmt)
            if rc == SQLITE_ROW { row?(stmt!) } else if rc == SQLITE_DONE { break } else {
                throw DBError.query(String(cString: sqlite3_errmsg(db)))
            }
        }
    }

    private func text(_ s: OpaquePointer, _ i: Int32) -> String? {
        sqlite3_column_type(s, i) == SQLITE_NULL ? nil : String(cString: sqlite3_column_text(s, i))
    }

    private func int(_ s: OpaquePointer, _ i: Int32) -> Int? {
        sqlite3_column_type(s, i) == SQLITE_NULL ? nil : Int(sqlite3_column_int64(s, i))
    }

    private func json<T: Decodable>(_ s: String?, as: T.Type) -> T? {
        guard let s, let d = s.data(using: .utf8) else { return nil }
        return try? JSONDecoder().decode(T.self, from: d)
    }

    private func jsonString<T: Encodable>(_ v: T) -> String {
        String(data: (try? JSONEncoder().encode(v)) ?? Data("null".utf8), encoding: .utf8)!
    }

    // MARK: - 매물

    func listings(includeFiltered: Bool, limit: Int = 500) throws -> [Listing] {
        let where_ = includeFiltered ? "" : "WHERE status NOT IN ('seeded', 'filtered')"
        var result: [Listing] = []
        try run("""
            SELECT id, search, title, price_jpy, image_url, url, buyee_url, first_seen, status, filter_reason,
                   score, score_reason, feedback
            FROM listings \(where_) ORDER BY first_seen DESC, rowid DESC LIMIT ?
            """, [.int(limit)]) { s in
            result.append(Listing(
                id: self.text(s, 0) ?? "",
                search: self.text(s, 1) ?? "",
                title: self.text(s, 2) ?? "",
                priceJPY: self.int(s, 3) ?? 0,
                imageURL: self.text(s, 4).flatMap(URL.init(string:)),
                url: self.text(s, 5).flatMap(URL.init(string:)),
                buyeeURL: self.text(s, 6).flatMap(URL.init(string:)),
                firstSeen: Date(timeIntervalSince1970: TimeInterval(self.int(s, 7) ?? 0)),
                status: self.text(s, 8) ?? "",
                filterReason: self.text(s, 9),
                score: self.int(s, 10),
                scoreReason: self.text(s, 11),
                feedback: self.int(s, 12)
            ))
        }
        return result
    }

    func setFeedback(listingID: String, value: Int?) throws {
        try run("UPDATE listings SET feedback = ?, feedback_at = ? WHERE id = ?",
                [.int(value), .int(value == nil ? nil : Int(Date().timeIntervalSince1970)), .text(listingID)])
    }

    /// 이번 달 채점 비용 (달러)
    func monthCostUSD() throws -> Double {
        let cal = Calendar.current
        let start = cal.date(from: cal.dateComponents([.year, .month], from: Date()))!
        var cost = 0.0
        try run("SELECT COALESCE(SUM(score_cost_usd), 0) FROM listings WHERE first_seen >= ?",
                [.int(Int(start.timeIntervalSince1970))]) { s in cost = sqlite3_column_double(s, 0) }
        return cost
    }

    func lastRun() throws -> RunInfo? {
        var info: RunInfo?
        try run("SELECT started_at, finished_at, new, notified, COALESCE(cost_usd, 0), errors FROM runs ORDER BY id DESC LIMIT 1") { s in
            info = RunInfo(
                startedAt: Date(timeIntervalSince1970: TimeInterval(self.int(s, 0) ?? 0)),
                finishedAt: self.int(s, 1).map { Date(timeIntervalSince1970: TimeInterval($0)) },
                new: self.int(s, 2) ?? 0,
                notified: self.int(s, 3) ?? 0,
                costUSD: sqlite3_column_double(s, 4),
                errors: self.json(self.text(s, 5), as: [String].self) ?? []
            )
        }
        return info
    }

    // MARK: - 검색어

    func searches() throws -> [Search] {
        var result: [Search] = []
        try run("""
            SELECT id, keyword, enabled, price_max, outer_price_max, exclude_keywords
            FROM searches ORDER BY sort_order, id
            """) { s in
            result.append(Search(
                id: Int64(self.int(s, 0) ?? 0),
                keyword: self.text(s, 1) ?? "",
                enabled: (self.int(s, 2) ?? 1) != 0,
                priceMax: self.int(s, 3),
                outerPriceMax: self.int(s, 4),
                excludeKeywords: self.json(self.text(s, 5), as: [String].self) ?? []
            ))
        }
        return result
    }

    func addSearch(keyword: String) throws {
        try run("""
            INSERT INTO searches (keyword, enabled, exclude_keywords, sort_order, created_at)
            VALUES (?, 1, '[]', (SELECT COALESCE(MAX(sort_order), 0) + 1 FROM searches), ?)
            """, [.text(keyword), .int(Int(Date().timeIntervalSince1970))])
    }

    func updateSearch(_ s: Search) throws {
        try run("""
            UPDATE searches SET keyword = ?, enabled = ?, price_max = ?, outer_price_max = ?, exclude_keywords = ?
            WHERE id = ?
            """, [.text(s.keyword), .int(s.enabled ? 1 : 0), .int(s.priceMax), .int(s.outerPriceMax),
                  .text(jsonString(s.excludeKeywords)), .int(Int(s.id))])
    }

    func deleteSearch(id: Int64) throws {
        try run("DELETE FROM searches WHERE id = ?", [.int(Int(id))])
    }

    // MARK: - 전체 설정

    func settings() throws -> GlobalSettings {
        var raw: [String: String] = [:]
        try run("SELECT key, value FROM settings") { s in
            if let k = self.text(s, 0) { raw[k] = self.text(s, 1) }
        }
        return GlobalSettings(
            taste: json(raw["taste"], as: String.self) ?? "",
            priceMax: json(raw["price_max"], as: Int?.self) ?? nil,
            outerPriceMax: json(raw["outer_price_max"], as: Int?.self) ?? nil,
            excludeKeywords: json(raw["exclude_keywords"], as: [String].self) ?? [],
            excludeCategories: json(raw["exclude_categories"], as: [Int].self) ?? []
        )
    }

    func saveSettings(_ g: GlobalSettings) throws {
        let pairs: [(String, String)] = [
            ("taste", jsonString(g.taste)),
            ("price_max", jsonString(g.priceMax)),
            ("outer_price_max", jsonString(g.outerPriceMax)),
            ("exclude_keywords", jsonString(g.excludeKeywords)),
            ("exclude_categories", jsonString(g.excludeCategories)),
        ]
        for (k, v) in pairs {
            try run("""
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """, [.text(k), .text(v)])
        }
    }
}
