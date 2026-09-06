import React from "react";

type Mode = "workspace" | "viewport" | null;

/** Fullscreen the document so portaled menus remain usable above the 3D tools. */
export function useSceneFullscreen(
  root: React.RefObject<HTMLDivElement | null>,
) {
  const [mode, setMode] = React.useState<Mode>(null);
  const current = React.useRef<Mode>(null);
  const previous = React.useRef<Mode>(null);
  const owned = React.useRef(false);
  const pending = React.useRef(false);
  const alive = React.useRef(true);
  const set = (value: Mode) => {
    current.current = value;
    setMode(value);
  };

  const leave = React.useCallback(async () => {
    current.current = null;
    if (alive.current) setMode(null);
    if (
      owned.current &&
      document.fullscreenElement === document.documentElement
    ) {
      owned.current = false;
      await document.exitFullscreen().catch(() => undefined);
    }
  }, []);

  React.useEffect(() => {
    alive.current = true;
    const changed = () => {
      if (!document.fullscreenElement && owned.current) {
        owned.current = false;
        current.current = null;
        setMode(null);
      }
    };
    const escape = (event: KeyboardEvent) => {
      // Some embedded hosts do not exit native fullscreen on Escape themselves.
      if (
        event.key === "Escape" &&
        !event.defaultPrevented &&
        current.current &&
        !document.querySelector('[role="dialog"][data-state="open"]')
      )
        void leave();
    };
    document.addEventListener("fullscreenchange", changed);
    window.addEventListener("keydown", escape);
    return () => {
      alive.current = false;
      document.removeEventListener("fullscreenchange", changed);
      window.removeEventListener("keydown", escape);
      void leave();
    };
  }, [leave]);

  React.useEffect(() => {
    if (!mode || !root.current) return;
    // Keep keyboard focus out of the covered app chrome without remounting WebGL.
    const hidden: {
      element: HTMLElement;
      inert: boolean;
      visibility: string;
    }[] = [];
    let branch: HTMLElement = root.current;
    while (branch.parentElement && branch.parentElement !== document.body) {
      for (const sibling of branch.parentElement.children) {
        if (sibling === branch || !(sibling instanceof HTMLElement)) continue;
        hidden.push({
          element: sibling,
          inert: sibling.inert,
          visibility: sibling.style.visibility,
        });
        sibling.inert = true;
        sibling.style.visibility = "hidden";
      }
      branch = branch.parentElement;
    }
    return () =>
      hidden.forEach(({ element, inert, visibility }) => {
        element.inert = inert;
        element.style.visibility = visibility;
      });
  }, [mode, root]);

  async function toggle(next: Exclude<Mode, null>) {
    if (pending.current) return;
    if (current.current === next) {
      if (next === "viewport" && previous.current === "workspace")
        set("workspace");
      else await leave();
      return;
    }
    previous.current = current.current;
    set(next);
    if (
      !document.fullscreenElement &&
      document.fullscreenEnabled &&
      document.documentElement.requestFullscreen
    ) {
      pending.current = true;
      try {
        await document.documentElement.requestFullscreen();
        owned.current = true;
        if (!alive.current || !current.current) await leave();
      } catch {
        // Embedded clients may deny native fullscreen; the full-window layout still works.
      } finally {
        pending.current = false;
      }
    }
  }
  return { mode, toggle };
}
