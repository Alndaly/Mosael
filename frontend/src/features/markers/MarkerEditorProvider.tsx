import React from "react";

const MarkerEditorContext = React.createContext<{
  activeId: string | null;
  setActiveId: React.Dispatch<React.SetStateAction<string | null>>;
} | null>(null);

/** One configuration popover per canvas, independent of multi-selection and undo history. */
export function MarkerEditorProvider({ enabled, children }: { enabled: boolean; children: React.ReactNode }) {
  const [activeId, setActiveId] = React.useState<string | null>(null);
  React.useEffect(() => { if (!enabled) setActiveId(null); }, [enabled]);
  const value = React.useMemo(() => ({ activeId: enabled ? activeId : null, setActiveId }), [activeId, enabled]);
  return <MarkerEditorContext.Provider value={value}>{children}</MarkerEditorContext.Provider>;
}

export function useMarkerEditor() {
  const context = React.useContext(MarkerEditorContext);
  if (!context) throw new Error("MarkerPin requires MarkerEditorProvider");
  const id = React.useId();
  const { activeId, setActiveId } = context;
  const activeIdRef = React.useRef(activeId);
  activeIdRef.current = activeId;
  const setOpen = React.useCallback((open: boolean) => {
    // A closing popover must not clear the marker that has just replaced it.
    setActiveId(current => open ? id : current === id ? null : current);
  }, [id, setActiveId]);
  React.useEffect(() => () => setOpen(false), [setOpen]);
  const onCloseAutoFocus = React.useCallback((event: Event) => {
    // Radix closes with an animation; its delayed focus restoration must not dismiss the new editor.
    if (activeIdRef.current !== null) event.preventDefault();
  }, []);
  return { open: activeId === id, setOpen, onCloseAutoFocus };
}
