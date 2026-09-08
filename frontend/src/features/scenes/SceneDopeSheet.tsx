import { HANDLE_ROW } from "@/lib/useResizableSidebar";
import React from "react";
import { Box, Video, Lightbulb, Folder, DiamondPlus, Trash2, Search, ZoomIn, ZoomOut, Scan } from "lucide-react";
import type { SceneContent, SceneShot } from "@/api/domains/scenes";
import { useI18n } from "@/app/preferences";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { trackRows, sameKey, type SceneKey } from "./sceneTracks";
import { SHOT_FPS } from "./encodeVideo";

/** One scroll surface keeps the ruler, object names and keys aligned, including scrollbar width. */
export function SceneDopeSheet({ content, shot, time, selectedId, playing, disabled = false, controls,
  onSeek, onSelect, onInsert, onDelete, onMove,
}: {
  controls?: React.ReactNode;
  content: SceneContent; shot: SceneShot; time: number; selectedId: string | null; playing: boolean; disabled?: boolean;
  onSeek: (time: number) => void; onSelect: (id: string) => void;
  onInsert: (id: string, time: number) => void;
  onDelete: (keys: SceneKey[]) => void;
  onMove: (keys: SceneKey[], delta: number) => boolean;
}) {
  const t = useI18n();
  const root = React.useRef<HTMLDivElement>(null);
  const cancelDrag = React.useRef<(() => void) | null>(null);
  React.useEffect(() => () => cancelDrag.current?.(), []);
  const [query, setQuery] = React.useState("");
  const [animatedOnly, setAnimatedOnly] = React.useState(false);
  const [keys, setKeys] = React.useState<SceneKey[]>([]);
  const [drag, setDrag] = React.useState<{keys: SceneKey[]; delta: number} | null>(null);
  const [height, setHeight] = React.useState(300);
  const [zoom, setZoom] = React.useState(1);
  // Keys outside a shorter shot stay visible and editable; the shaded area marks the playback end.
  const end = Math.max(shot.duration, ...content.objects.flatMap(o => o.track.map(f => f.time)), 0);
  const rows = trackRows(content, shot).filter(row =>
    row.object.name.toLocaleLowerCase().includes(query.toLocaleLowerCase()) && (!animatedOnly || row.times.length > 0));
  const selectedKeys = keys.filter(key => rows.some(row => row.object.id === key.id && row.times.some(time => sameKey(key, {id: key.id, time}))));
  const selectedObject = rows.find(row => row.object.id === selectedId)?.object;
  const at = (value: number) => end > 0 ? value / end * 100 : 0;
  const snap = (value: number) => Math.max(0, Math.min(end, Math.round(value * SHOT_FPS) / SHOT_FPS));
  React.useEffect(() => { setKeys([]); setDrag(null); }, [shot.id]);
  const focus = () => root.current?.focus({preventScroll: true});
  function selectKey(key: SceneKey, extend: boolean) {
    const exists = selectedKeys.some(one => sameKey(one, key));
    const next = extend ? (exists ? selectedKeys.filter(one => !sameKey(one, key)) : [...selectedKeys, key]) : exists ? selectedKeys : [key];
    setKeys(next); onSelect(key.id); onSeek(key.time); focus();
    return next;
  }
  function pointerTime(event: React.PointerEvent<HTMLElement>) {
    const rect = event.currentTarget.getBoundingClientRect();
    return rect.width > 0 ? snap((event.clientX - rect.left) / rect.width * end) : time;
  }
  function scrub(event: React.PointerEvent<HTMLElement>, id?: string) {
    if (event.button !== 0 || disabled) return;
    event.preventDefault(); focus(); setKeys([]);
    if (id) onSelect(id);
    event.currentTarget.setPointerCapture?.(event.pointerId);
    onSeek(pointerTime(event));
  }
  function dragKey(event: React.PointerEvent<HTMLButtonElement>, key: SceneKey) {
    if (disabled || event.button !== 0) return;
    event.stopPropagation(); event.preventDefault();
    const next = selectKey(key, event.shiftKey || event.metaKey || event.ctrlKey);
    if (!next.some(one => sameKey(one, key))) return;
    cancelDrag.current?.();
    const width = event.currentTarget.parentElement!.getBoundingClientRect().width;
    const start = event.clientX;
    const pointerId = event.pointerId;
    const target = event.currentTarget;
    target.setPointerCapture?.(pointerId);
    let delta = 0;
    const move = (e: PointerEvent) => {
      if (e.pointerId !== pointerId || width <= 0) return;
      const raw = Math.round((e.clientX - start) / width * end * SHOT_FPS) / SHOT_FPS;
      delta = Math.min(end - Math.max(...next.map(k => k.time)), Math.max(-Math.min(...next.map(k => k.time)), raw));
      setDrag({keys: next, delta});
    };
    const finish = (e: PointerEvent) => {
      if (e.pointerId !== pointerId) return;
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", cancel);
      cancelDrag.current = null;
      setDrag(null);
      if (Math.abs(delta) > 0.0001 && onMove(next, delta)) {
        setKeys(next.map(k => ({...k, time: Number((k.time + delta).toFixed(6))})));
        onSeek(Number((key.time + delta).toFixed(6)));
      }
    };
    const cancel = () => {
      window.removeEventListener("pointermove", move);
      window.removeEventListener("pointerup", finish);
      window.removeEventListener("pointercancel", cancel);
      cancelDrag.current = null;
      setDrag(null);
    };
    cancelDrag.current = cancel;
    window.addEventListener("pointermove", move);
    window.addEventListener("pointerup", finish);
    window.addEventListener("pointercancel", cancel);
  }
  const deleteKeys = () => { if (selectedKeys.length && !disabled) { onDelete(selectedKeys); setKeys([]); } };
  return (
    <div ref={root} className="scene-dope" role="group" aria-label={t("sceneAnimTimeline")} tabIndex={-1}
      style={{height}} onKeyDown={event => {
        if ((event.target as HTMLElement).closest("input,textarea,[role=combobox]")) return;
        if (["delete", "backspace", "x"].includes(event.key.toLowerCase())) {
          event.preventDefault(); event.stopPropagation(); deleteKeys();
        } else if (event.key === "Escape") { cancelDrag.current?.(); setKeys([]); event.stopPropagation(); }
        else if ((event.ctrlKey || event.metaKey) && event.key === "a") {
          event.preventDefault(); setKeys(rows.flatMap(row => row.times.map(time => ({id: row.object.id, time}))));
        } else if (!disabled && event.shiftKey && ["ArrowLeft", "ArrowRight"].includes(event.key) && selectedKeys.length) {
          event.preventDefault(); event.stopPropagation();
          const delta = (event.key === "ArrowLeft" ? -1 : 1) / SHOT_FPS;
          if (onMove(selectedKeys, delta)) setKeys(selectedKeys.map(key => ({...key, time: Number((key.time + delta).toFixed(6))})));
        }
      }}>
      <div className={`scene-dope-resize ${HANDLE_ROW}`} role="separator" aria-orientation="horizontal" aria-label={t("sceneAnimResize")}
        aria-valuemin={160} aria-valuemax={600} aria-valuenow={height} tabIndex={0}
        onKeyDown={event => { if (["ArrowUp", "ArrowDown"].includes(event.key)) {event.preventDefault(); event.stopPropagation(); setHeight(h => Math.max(160, Math.min(600, h + (event.key === "ArrowUp" ? 32 : -32))));} }}
        onPointerDown={event => {event.preventDefault(); event.currentTarget.setPointerCapture(event.pointerId);}}
        onPointerMove={event => {if (event.currentTarget.hasPointerCapture(event.pointerId)) setHeight(h => Math.max(160, Math.min(600, h - event.movementY)));}}
      ><span /></div>
      {controls}
      <div className="scene-dope-toolbar">
        <label className="scene-dope-search"><Search size={14}/><Input className="h-7 text-ui-xs" aria-label={t("sceneAnimSearch")} placeholder={t("sceneAnimSearch")} value={query} onChange={e => setQuery(e.target.value)} /></label>
        <Button size="xs" variant={animatedOnly ? "secondary" : "outline"} aria-pressed={animatedOnly} onClick={() => setAnimatedOnly(!animatedOnly)}>{t("sceneAnimAnimated")}</Button>
        <span className="scene-dope-count">{rows.length} / {content.objects.length}</span>
        <div className="scene-spacer" />
        <Button size="xs" variant="outline" disabled={!selectedObject || disabled} title={`${t("sceneAnimInsert")} · I`} onClick={() => selectedObject && onInsert(selectedObject.id, time)}><DiamondPlus />{t("sceneAnimInsert")}</Button>
        <Button size="icon-xs" variant="outline" disabled={!selectedKeys.length || disabled} title={t("sceneAnimDelete")} aria-label={t("sceneAnimDelete")} onClick={deleteKeys}><Trash2 /></Button>
        <span className="scene-tool-divider" aria-hidden="true" />
        <Button size="icon-xs" variant="ghost" disabled={zoom === 1} aria-label={t("sceneAnimZoomOut")} title={t("sceneAnimZoomOut")} onClick={() => setZoom(z => Math.max(1, z - 1))}><ZoomOut /></Button>
        <Button size="icon-xs" variant="ghost" disabled={zoom === 8} aria-label={t("sceneAnimZoomIn")} title={t("sceneAnimZoomIn")} onClick={() => setZoom(z => Math.min(8, z + 1))}><ZoomIn /></Button>
        <Button size="icon-xs" variant="ghost" aria-label={t("sceneAnimFit")} title={t("sceneAnimFit")} onClick={() => setZoom(1)}><Scan /></Button>
      </div>
      <div className="scene-dope-scroll">
        <div className="scene-dope-sheet" style={{minWidth: 560 * zoom}}>
          <div className="scene-dope-ruler">
            <span className="scene-dope-heading">{t("sceneAnimObjects")}</span>
            <div className="scene-dope-lane"><div className="scene-dope-track" role="slider" tabIndex={0} aria-label={t("sceneAnimTime")} aria-valuemin={0} aria-valuemax={end} aria-valuenow={time}
              onPointerDown={e => scrub(e)} onPointerMove={e => {if (e.currentTarget.hasPointerCapture?.(e.pointerId)) onSeek(pointerTime(e));}}
              onKeyDown={e => {if (["ArrowLeft", "ArrowRight", "Home", "End"].includes(e.key)) {e.preventDefault(); e.stopPropagation(); onSeek(e.key === "Home" ? 0 : e.key === "End" ? end : snap(time + (e.key === "ArrowRight" ? 1 : -1) / SHOT_FPS));}}}>
              {Array.from({length: 11}, (_, i) => <span className="scene-dope-tick" key={i} style={{left: `${i * 10}%`}}>{(end * i / 10).toFixed(end < 10 ? 1 : 0)}s</span>)}
              <i className="scene-dope-cursor" style={{left: `${at(time)}%`}} />
            </div></div>
          </div>
          {rows.map(row => {
            const Icon = row.object.kind === "camera" ? Video : row.object.kind === "light" ? Lightbulb : row.object.kind === "group" ? Folder : Box;
            return <div className="scene-dope-row" key={row.object.id} data-selected={row.object.id === selectedId || undefined}>
              <button className="scene-dope-name" title={row.object.name} aria-pressed={row.object.id === selectedId} onClick={() => {setKeys([]); onSelect(row.object.id); focus();}}>
                <Icon size={14}/><span>{row.object.name}</span><small>{row.times.length || "—"}</small>
              </button>
              <div className="scene-dope-lane"><div className="scene-dope-track" role="presentation"
                onPointerDown={e => scrub(e, row.object.id)} onPointerMove={e => {if (e.currentTarget.hasPointerCapture?.(e.pointerId)) onSeek(pointerTime(e));}}>
                {shot.duration < end && <span className="scene-dope-outside" style={{left: `${at(shot.duration)}%`}}/>}
                {row.times.map(value => {
                  const key = {id: row.object.id, time: value};
                  const selected = selectedKeys.some(one => sameKey(one, key));
                  const displayTime = value + (drag?.keys.some(one => sameKey(one, key)) ? drag.delta : 0);
                  return <button key={value} className="scene-dope-key" style={{left: `${at(displayTime)}%`}}
                    aria-label={`${row.object.name} · ${value.toFixed(2)}s`} title={`${row.object.name} · ${value.toFixed(2)}s`} aria-pressed={selected}
                    onPointerDown={e => dragKey(e, key)} onClick={e => {e.stopPropagation(); if (e.detail === 0) selectKey(key, e.shiftKey);}}
                  ><i /></button>;
                })}
                <i className="scene-dope-playhead" aria-hidden style={{left: `${at(time)}%`}} data-playing={playing || undefined}/>
              </div></div>
            </div>;
          })}
          {!rows.length && <p className="scene-dope-empty">{t("sceneAnimEmpty")}</p>}
        </div>
      </div>
      <div className="scene-dope-footer"><span>{t("sceneAnimHint")}</span><span>{SHOT_FPS} fps · {selectedKeys.length} {t("sceneAnimSelected")}</span></div>
    </div>
  );
}
