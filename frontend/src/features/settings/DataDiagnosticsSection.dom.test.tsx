/** @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import React from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

vi.mock("@/app/preferences", () => ({ useI18n: () => (key: string) => key }));
const api = vi.hoisted(() => vi.fn());
vi.mock("@/api/client", () => ({ api, getAuthToken: () => "test-token", isCustomServer: () => false }));

import { DataDiagnosticsSection } from "@/features/settings/DataDiagnosticsSection";

afterEach(() => {
  delete (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop;
  api.mockReset();
});

describe("数据与诊断设置", () => {
  it("one click exports a desktop diagnostic bundle", async () => {
    const exportDiagnostics = vi.fn().mockResolvedValue({ status: "saved", path: "/tmp/diagnostics.zip" });
    (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = {
      platform: "darwin",
      data: { exportDiagnostics },
    };

    render(<DataDiagnosticsSection />);
    await userEvent.click(screen.getByRole("button", { name: "dataDiagnosticsExport" }));

    expect(exportDiagnostics).toHaveBeenCalledOnce();
  });

  it("streams a full backup through the desktop bridge", async () => {
    const createBackup = vi.fn().mockResolvedValue({ status: "saved", path: "/tmp/Mosael.mosael-backup" });
    (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = {
      platform: "darwin",
      data: { exportDiagnostics: vi.fn(), createBackup },
    };

    render(<DataDiagnosticsSection />);
    await userEvent.click(screen.getByRole("button", { name: "dataDiagnosticsBackupCreate" }));

    expect(createBackup).toHaveBeenCalledWith("test-token");
  });

  it("requires confirmation, validates the archive, then applies it on restart", async () => {
    const applyRestore = vi.fn().mockResolvedValue({ status: "restarting" });
    api.mockResolvedValue({ stage_id: "b".repeat(32), source_app_version: "1.0.0" });
    (window as unknown as { mosaelDesktop?: unknown }).mosaelDesktop = {
      platform: "darwin",
      data: { exportDiagnostics: vi.fn(), createBackup: vi.fn(), applyRestore },
    };
    render(<DataDiagnosticsSection />);

    await userEvent.upload(
      screen.getByLabelText("dataDiagnosticsRestoreFile"),
      new File(["backup"], "safe.mosael-backup", { type: "application/zip" }),
    );
    expect(applyRestore).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "dataDiagnosticsRestoreConfirm" }));

    expect(api).toHaveBeenCalledWith(
      "/api/settings/data/restore/stage",
      expect.objectContaining({ method: "POST", body: expect.any(FormData) }),
    );
    expect(applyRestore).toHaveBeenCalledWith("b".repeat(32));
  });
});
