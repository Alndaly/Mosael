import React from "react";

/** Fullscreen the document so portaled menus remain usable above the 3D tools. */
export function useSceneFullscreen(
  root: React.RefObject<HTMLDivElement | null>,
) {
  const [active, setActive] = React.useState(false);
  const current = React.useRef(false);
  const owned = React.useRef(false);
  const pending = React.useRef(false);
  const alive = React.useRef(true);
  const set = (value: boolean) => {
    current.current = value;
    setActive(value);
  };

  const leave = React.useCallback(async () => {
    current.current = false;
    if (alive.current) setActive(false);
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
        current.current = false;
        setActive(false);
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
    if (!active || !root.current) return;
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
  }, [active, root]);

  async function toggle() {
    if (pending.current) return;
    if (current.current) {
      await leave();
      return;
    }
    set(true);
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
  return { active, toggle };
}
