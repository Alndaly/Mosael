import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CalendarClock, Play, Timer } from "lucide-react";

import { api, type Job, type Project, type RunScheduledTaskResponse, type ScheduledTask, type Workspace } from "@/api/client";

export function SchedulerView({ workspace, project }: { workspace: Workspace; project: Project | null }) {
  const qc = useQueryClient();
  const tasks = useQuery({
    queryKey: ["scheduled-tasks", workspace.id],
    queryFn: () => api<ScheduledTask[]>(`/api/scheduled-tasks?workspace_id=${workspace.id}`),
  });
  const jobs = useQuery({
    queryKey: ["jobs", workspace.id],
    queryFn: () => api<Job[]>(`/api/jobs?workspace_id=${workspace.id}`),
  });
  const createTask = useMutation({
    mutationFn: () =>
      api<ScheduledTask>("/api/scheduled-tasks", {
        method: "POST",
        body: JSON.stringify({
          workspace_id: workspace.id,
          project_id: project?.id ?? null,
          name: "每小时渲染检查",
          kind: "render",
          trigger_type: "interval",
          schedule: { seconds: 3600 },
          payload: { project_id: project?.id ?? null },
        }),
      }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspace.id] }),
  });
  const runTask = useMutation({
    mutationFn: (taskId: string) => api<RunScheduledTaskResponse>(`/api/scheduled-tasks/${taskId}/run`, { method: "POST" }),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: ["scheduled-tasks", workspace.id] });
      qc.invalidateQueries({ queryKey: ["jobs", workspace.id] });
    },
  });

  return (
    <div className="feature-view">
      <header className="feature-head">
        <div>
          <h1>定时任务</h1>
          <p>把渲染、生成、素材检查等后台工作统一排队。</p>
        </div>
        <button onClick={() => createTask.mutate()}><CalendarClock size={16} /> 新建任务</button>
      </header>

      <section className="feature-grid two">
        <div className="panel feature-panel">
          <div className="panel-head"><h2>任务</h2></div>
          <div className="task-list">
            {(tasks.data ?? []).map((task) => (
              <div className="task-row" key={task.id}>
                <Timer size={16} />
                <div>
                  <strong>{task.name}</strong>
                  <small>{task.kind} · {task.trigger_type} · {task.next_run_at ?? "manual"}</small>
                </div>
                <button onClick={() => runTask.mutate(task.id)}><Play size={14} /></button>
              </div>
            ))}
            {tasks.data?.length === 0 && <div className="empty-inline">还没有定时任务</div>}
          </div>
        </div>

        <div className="panel feature-panel">
          <div className="panel-head"><h2>最近 Job</h2></div>
          <div className="job-list">
            {(jobs.data ?? []).slice(0, 8).map((job) => (
              <div className="job-row" key={job.id}>
                <Play size={16} />
                <div>
                  <strong>{job.kind}</strong>
                  <small>{job.status} · {job.message}</small>
                </div>
              </div>
            ))}
            {jobs.data?.length === 0 && <div className="empty-inline">还没有后台任务</div>}
          </div>
        </div>
      </section>
    </div>
  );
}
