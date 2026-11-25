import Foundation

/// 渲染层推来的一件正在发生的事。字段和 `frontend/src/components/island/liveActivities.ts`
/// 的 wire 形状一一对应;Native 侧不认识业务,只按状态摆。
struct IslandActivity: Codable, Identifiable, Equatable {
    let id: String
    let state: String
    let title: String
    let detail: String?
    let progress: Double?
    let priority: Int?

    var isOngoing: Bool { state == "ongoing" }
    var isDone: Bool { state == "done" }
    var isFailed: Bool { state == "failed" }
}

struct IslandState: Codable {
    let activities: [IslandActivity]
}

struct IslandEvent: Codable {
    let type: String
    let id: String?
}
