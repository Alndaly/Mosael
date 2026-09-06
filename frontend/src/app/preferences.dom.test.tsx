/** @vitest-environment jsdom */
import React from "react";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { PreferencesProvider, usePreferences } from "./preferences";
import { INTERFACE_FONTS } from "./interfaceFonts";

vi.mock("@/api/client", () => ({ setApiLocale: vi.fn() }));
vi.mock("./interfaceFonts", async (original) => ({ ...await original<typeof import("./interfaceFonts")>(), loadInterfaceFont: vi.fn(() => Promise.resolve()) }));
afterEach(() => { cleanup(); localStorage.clear(); document.documentElement.style.removeProperty("--font-sans"); });
function Controls() {
  const { font, setFont, setTheme, setLocale } = usePreferences();
  return <><output>{font}</output><button onClick={() => setFont("noto-serif")}>Serif</button><button onClick={() => setTheme("dark")}>Dark</button><button onClick={() => setLocale("en-US")}>English</button></>;
}
const mount = () => render(<PreferencesProvider><Controls /></PreferencesProvider>);

it("applies a global font, keeps it across theme/locale changes, and restores it on restart", () => {
  localStorage.setItem("mosael.preferences", JSON.stringify({ theme: "light", locale: "zh-CN", voiceDock: true }));
  const view = mount();
  expect(screen.getByRole("status")).toHaveTextContent("default");
  fireEvent.click(screen.getByText("Serif"));
  fireEvent.click(screen.getByText("Dark"));
  fireEvent.click(screen.getByText("English"));
  expect(document.documentElement.style.getPropertyValue("--font-sans")).toBe(INTERFACE_FONTS.find(font => font.id === "noto-serif")!.family);
  expect(JSON.parse(localStorage.getItem("mosael.preferences")!)).toEqual({ theme: "dark", locale: "en-US", voiceDock: true, font: "noto-serif" });
  view.unmount();
  mount();
  expect(screen.getByRole("status")).toHaveTextContent("noto-serif");
});

it("falls back safely when a saved font is unavailable", () => {
  localStorage.setItem("mosael.preferences", JSON.stringify({ font: "removed-font" }));
  mount();
  expect(screen.getByRole("status")).toHaveTextContent("default");
  expect(document.documentElement.style.getPropertyValue("--font-sans")).toContain("Inter Variable");
});
