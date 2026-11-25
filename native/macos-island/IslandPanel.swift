import AppKit
import Combine
import SwiftUI

/// 刘海几何。不同 MacBook 的 cutout 宽度不同,必须从 NSScreen 读,不能写死。
struct NotchGeometry {
    let screenFrame: NSRect
    let hasNotch: Bool
    let notchWidth: CGFloat
    let menuBarHeight: CGFloat
    let wingWidth: CGFloat = 104
    let wingGap: CGFloat = 2
    let wingHeight: CGFloat = 26
    let panelHeight: CGFloat = 380

    var topMargin: CGFloat { max(2, (menuBarHeight - wingHeight) / 2) }
    /// 紧凑态只包住刘海左右两侧;展开时才变宽成 NoobX 那种大面板。
    var compactWidth: CGFloat {
        hasNotch ? notchWidth + (wingWidth + wingGap) * 2 : wingWidth * 2 + 4
    }
    var expandedWidth: CGFloat { min(520, screenFrame.width - 96) }
    var panelWidth: CGFloat { expandedWidth }
    func expandedHeight(count: Int) -> CGFloat { min(280, max(88, CGFloat(count) * 52 + 8)) }

    static func current() -> NotchGeometry {
        // 跟着鼠标所在屏幕走:外接屏没有刘海时,岛就落在那块屏的菜单栏,不能留在内置屏上。
        let mouse = NSEvent.mouseLocation
        let screen = NSScreen.screens.first { NSMouseInRect(mouse, $0.frame, false) }
            ?? NSScreen.main
            ?? NSScreen.screens.first { $0.safeAreaInsets.top > 0 }
            ?? NSScreen.screens[0]
        let top = screen.safeAreaInsets.top
        var notchWidth: CGFloat = 0
        if top > 0, let left = screen.auxiliaryTopLeftArea, let right = screen.auxiliaryTopRightArea {
            notchWidth = screen.frame.width - left.width - right.width
        }
        let hasNotch = top > 0 && notchWidth > 80
        return NotchGeometry(
            screenFrame: screen.frame,
            hasNotch: hasNotch,
            notchWidth: hasNotch ? notchWidth : 0,
            menuBarHeight: hasNotch ? top : 25
        )
    }
}
/// 只让岛本身接鼠标;透明区域返回 nil,点击穿过到下面的菜单栏 / 窗口。
/// 允许窗口顶边越过菜单栏。默认的 `constrainFrameRect` 会把普通窗口压在菜单栏下面,
/// 而灵动岛必须盖在菜单栏/刘海里。
final class IslandPanel: NSPanel {
    override func constrainFrameRect(_ frameRect: NSRect, to screen: NSScreen?) -> NSRect {
        frameRect
    }
}

final class IslandHostingView: NSHostingView<AnyView> {
    var interactiveRects: () -> [CGRect] = { [] }

    override func hitTest(_ point: NSPoint) -> NSView? {
        let local = convert(point, from: superview)
        guard interactiveRects().contains(where: { $0.contains(local) }) else { return nil }
        return super.hitTest(point)
    }
}

final class IslandPanelController {
    private let store = IslandStore()
    private let panel: IslandPanel
    private let hosting: IslandHostingView
    private var geometry = NotchGeometry.current()
    private var cancellables: Set<AnyCancellable> = []
    private var hoverTimer: Timer?

    init() {
        panel = IslandPanel(
            contentRect: .zero,
            styleMask: [.borderless, .nonactivatingPanel],
            backing: .buffered,
            defer: false
        )
        panel.isOpaque = false
        panel.backgroundColor = .clear
        panel.hasShadow = false
        panel.collectionBehavior = [.canJoinAllSpaces, .stationary, .fullScreenAuxiliary]
        panel.isMovable = false
        panel.isReleasedWhenClosed = false
        panel.hidesOnDeactivate = false
        panel.becomesKeyOnlyIfNeeded = true
        // `isFloatingPanel` 会把 level 改回 .floating(3);必须在它之后再设 statusBar。
        panel.isFloatingPanel = true
        panel.level = .statusBar
        panel.ignoresMouseEvents = false
        panel.acceptsMouseMovedEvents = true

        hosting = IslandHostingView(rootView: AnyView(EmptyView()))
        hosting.interactiveRects = { [weak self] in self?.interactiveRects() ?? [] }
        panel.contentView = hosting

        hosting.rootView = AnyView(
            IslandView(store: store, geometry: geometry) { [weak self] id in
                self?.emitOpen(id)
            }
        )

        store.$activities
            .receive(on: RunLoop.main)
            .sink { [weak self] activities in self?.activitiesChanged(activities) }
            .store(in: &cancellables)
        store.$open
            .receive(on: RunLoop.main)
            .sink { [weak self] _ in self?.hosting.needsLayout = true }
            .store(in: &cancellables)

        NotificationCenter.default.addObserver(
            self,
            selector: #selector(screenParametersChanged),
            name: NSApplication.didChangeScreenParametersNotification,
            object: nil
        )
        NSWorkspace.shared.notificationCenter.addObserver(
            self,
            selector: #selector(screenParametersChanged),
            name: NSWorkspace.didActivateApplicationNotification,
            object: nil
        )
    }

    func apply(_ activities: [IslandActivity]) {
        store.apply(activities)
    }

    @objc private func screenParametersChanged() {
        reposition()
    }

    private func activitiesChanged(_ activities: [IslandActivity]) {
        if activities.isEmpty {
            stopHoverTracking()
            panel.orderOut(nil)
            return
        }
        reposition()
        panel.orderFrontRegardless()
        startHoverTracking()
        hosting.needsLayout = true
    }

    /// SwiftUI 的 onHover 在透明非激活 panel 上不稳;这里用系统鼠标位置做唯一判据,
    /// 也让「离开后收起」不依赖某个子视图是否收到 mouseExited。
    private func startHoverTracking() {
        guard hoverTimer == nil else { return }
        hoverTimer = Timer.scheduledTimer(withTimeInterval: 0.10, repeats: true) { [weak self] _ in
            self?.trackHover()
        }
    }

    private func stopHoverTracking() {
        hoverTimer?.invalidate()
        hoverTimer = nil
    }

    private func trackHover() {
        guard !store.activities.isEmpty else { return }
        let mouse = NSEvent.mouseLocation
        let point = NSPoint(x: mouse.x - panel.frame.minX, y: mouse.y - panel.frame.minY)
        let rects = interactiveRects()
        let inside = rects.contains { $0.insetBy(dx: -4, dy: -4).contains(point) }
        if inside != store.open {
            withAnimation(.spring(response: 0.34, dampingFraction: 0.86)) { store.open = inside }
        }
    }

    private func reposition() {
        geometry = NotchGeometry.current()
        let frame = NSRect(
            x: geometry.screenFrame.midX - geometry.panelWidth / 2,
            y: geometry.screenFrame.maxY - geometry.panelHeight,
            width: geometry.panelWidth,
            height: geometry.panelHeight
        )
        panel.setFrame(frame, display: true)
        hosting.rootView = AnyView(
            IslandView(store: store, geometry: geometry) { [weak self] id in self?.emitOpen(id) }
        )
    }

    private func interactiveRects() -> [CGRect] {
        let wingY = geometry.panelHeight - geometry.menuBarHeight + (geometry.menuBarHeight - geometry.wingHeight) / 2
        let leftX = (geometry.panelWidth - geometry.compactWidth) / 2
        let left = CGRect(x: leftX, y: wingY, width: geometry.wingWidth, height: geometry.wingHeight)
        let right = CGRect(x: leftX + geometry.compactWidth - geometry.wingWidth, y: wingY, width: geometry.wingWidth, height: geometry.wingHeight)
        guard store.open, !store.activities.isEmpty else { return [left, right] }
        let height = geometry.expandedHeight(count: store.activities.count)
        let expanded = CGRect(
            x: (geometry.panelWidth - geometry.expandedWidth) / 2,
            y: geometry.panelHeight - geometry.menuBarHeight - height,
            width: geometry.expandedWidth,
            height: height
        )
        return [left, right, expanded]
    }

    private func emitOpen(_ id: String) {
        writeEvent(IslandEvent(type: "open", id: id))
    }
}

func writeEvent(_ event: IslandEvent) {
    guard let data = try? JSONEncoder().encode(event), let text = String(data: data, encoding: .utf8) else { return }
    FileHandle.standardOutput.write(Data((text + "\n").utf8))
}
