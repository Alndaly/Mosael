import SwiftUI

/// 灵动岛的外观。
///
/// **一块整体,不是两块药丸拼起来。** 顶部中间是硬件刘海,用 mask 挖掉;黑色面从
/// 刘海左右两侧的菜单栏一直延伸到展开列表,中间没有描边、没有第二层卡片。
struct IslandView: View {
    @ObservedObject var store: IslandStore
    let geometry: NotchGeometry
    let onOpen: (String) -> Void

    @State private var closeWork: DispatchWorkItem?

    private var expandedHeight: CGFloat { CGFloat(store.activities.count) * 52 + 8 }
    private var surfaceHeight: CGFloat {
        geometry.menuBarHeight + (store.open ? expandedHeight : 0)
    }

    var body: some View {
        ZStack(alignment: .top) {
            RoundedRectangle(cornerRadius: 18, style: .continuous)
                .fill(Color.black.opacity(0.96))
                .frame(width: geometry.panelWidth, height: surfaceHeight, alignment: .top)
                .animation(.spring(response: 0.30, dampingFraction: 0.90), value: surfaceHeight)

            VStack(spacing: 0) {
                HStack(spacing: 0) {
                    leftWing
                    Spacer().frame(width: geometry.hasNotch ? geometry.notchWidth + geometry.wingGap * 2 : 4)
                    rightWing
                }
                .frame(width: geometry.panelWidth, height: geometry.menuBarHeight)

                expandedRows
                    .frame(height: store.open ? expandedHeight : 0, alignment: .top)
                    .clipped()
                    .opacity(store.open ? 1 : 0)
                    .allowsHitTesting(store.open)
                    .animation(.spring(response: 0.30, dampingFraction: 0.90), value: store.open)
            }
            .frame(width: geometry.panelWidth, height: surfaceHeight, alignment: .top)
        }
        .frame(width: geometry.panelWidth, height: geometry.panelHeight, alignment: .top)
        .background(Color.clear)
        .onHover { inside in
            guard store.activities.count > 1 || store.lead?.detail != nil else { return }
            schedule(inside)
        }
    }

    private func schedule(_ open: Bool) {
        closeWork?.cancel()
        let work = DispatchWorkItem {
            withAnimation(.spring(response: 0.30, dampingFraction: 0.90)) { store.open = open }
        }
        closeWork = work
        DispatchQueue.main.asyncAfter(deadline: .now() + (open ? 0.08 : 0.20), execute: work)
    }

    private var leftWing: some View {
        Button { store.open = false; if let id = store.lead?.id { onOpen(id) } } label: {
            HStack(spacing: 7) {
                Circle()
                    .fill(statusColor)
                    .frame(width: 6, height: 6)
                Text(store.lead?.title ?? "")
                    .font(.system(size: 11.5, weight: .medium))
                    .foregroundStyle(.white.opacity(0.94))
                    .lineLimit(1)
                    .truncationMode(.middle)
                Spacer(minLength: 0)
            }
            .padding(.horizontal, 11)
            .frame(width: geometry.wingWidth, height: geometry.wingHeight)
        }
        .buttonStyle(.plain)
        .help(store.lead?.detail ?? store.lead?.title ?? "")
        .accessibilityLabel(store.lead?.title ?? "")
    }

    private var rightWing: some View {
        Button { store.open = false; if let id = store.lead?.id { onOpen(id) } } label: {
            HStack(spacing: 6) {
                Spacer(minLength: 0)
                ActivityMark(activity: store.lead)
                    .scaleEffect(0.92)
                if let progress = store.lead?.progress, store.lead?.isOngoing == true {
                    Text(percent(progress))
                        .font(.system(size: 10.5, weight: .medium).monospacedDigit())
                        .foregroundStyle(.white.opacity(0.62))
                }
                if store.activities.count > 1 {
                    Text("+\(store.activities.count - 1)")
                        .font(.system(size: 9.5, weight: .semibold))
                        .foregroundStyle(.white.opacity(0.86))
                        .padding(.horizontal, 5)
                        .padding(.vertical, 1)
                        .background(Capsule().fill(Color.white.opacity(0.14)))
                }
            }
            .padding(.horizontal, 11)
            .frame(width: geometry.wingWidth, height: geometry.wingHeight)
        }
        .buttonStyle(.plain)
        .help(store.lead?.detail ?? store.lead?.title ?? "")
        .accessibilityLabel(store.lead?.title ?? "")
    }

    private var statusColor: Color {
        guard let state = store.lead?.state else { return .white }
        if state == "done" { return Color(red: 0.35, green: 0.85, blue: 0.55) }
        if state == "failed" { return Color(red: 1.0, green: 0.42, blue: 0.42) }
        return .white.opacity(0.82)
    }

    private var expandedRows: some View {
        VStack(spacing: 0) {
            ForEach(store.activities) { activity in
                Button {
                    store.open = false
                    onOpen(activity.id)
                } label: {
                    HStack(spacing: 10) {
                        ActivityMark(activity: activity)
                        VStack(alignment: .leading, spacing: 2) {
                            Text(activity.title)
                                .font(.system(size: 12, weight: .medium))
                                .foregroundStyle(.white)
                                .lineLimit(1)
                            if let detail = activity.detail, !detail.isEmpty {
                                Text(detail)
                                    .font(.system(size: 10))
                                    .foregroundStyle(.white.opacity(0.52))
                                    .lineLimit(1)
                            }
                        }
                        Spacer(minLength: 0)
                        if activity.isOngoing, let progress = activity.progress {
                            Text(percent(progress))
                                .font(.system(size: 10, weight: .medium).monospacedDigit())
                                .foregroundStyle(.white.opacity(0.52))
                        }
                    }
                    .padding(.horizontal, 14)
                    .frame(height: 52)
                    .contentShape(Rectangle())
                    .background(Color.white.opacity(0.001))
                }
                .buttonStyle(.plain)
            }
        }
        .padding(.vertical, 4)
    }

    private func percent(_ progress: Double) -> String {
        "\(Int((min(max(progress, 0), 1) * 100).rounded()))%"
    }
}


private struct ActivityMark: View {
    let activity: IslandActivity?

    var body: some View {
        Group {
            if activity?.isDone == true {
                Image(systemName: "checkmark.circle.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Color(red: 0.35, green: 0.85, blue: 0.55))
            } else if activity?.isFailed == true {
                Image(systemName: "exclamationmark.circle.fill")
                    .font(.system(size: 16, weight: .semibold))
                    .foregroundStyle(Color(red: 1.0, green: 0.42, blue: 0.42))
            } else if let progress = activity?.progress {
                ZStack {
                    Circle().stroke(Color.white.opacity(0.18), lineWidth: 2)
                    Circle()
                        .trim(from: 0, to: min(max(progress, 0), 1))
                        .stroke(Color.white, style: StrokeStyle(lineWidth: 2, lineCap: .round))
                        .rotationEffect(.degrees(-90))
                        .animation(.easeOut(duration: 0.25), value: progress)
                    Circle().fill(Color.white.opacity(0.90)).frame(width: 4.5, height: 4.5)
                }
                .frame(width: 16, height: 16)
            } else {
                ProgressView()
                    .progressViewStyle(.circular)
                    .controlSize(.small)
                    .tint(.white)
                    .scaleEffect(0.72)
                    .frame(width: 16, height: 16)
            }
        }
        .frame(width: 18, height: 18)
    }
}
