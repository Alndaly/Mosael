import Foundation
import SwiftUI

/// 面板的数据源:只保存渲染层推来的快照,不反查 Mosael。
final class IslandStore: ObservableObject {
    @Published private(set) var activities: [IslandActivity] = []
    @Published var open = false

    var lead: IslandActivity? { activities.first }
    var hasActivities: Bool { !activities.isEmpty }

    func apply(_ next: [IslandActivity]) {
        activities = next
        if next.isEmpty { open = false }
    }
}
