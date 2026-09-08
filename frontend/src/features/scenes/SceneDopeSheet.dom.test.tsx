/** @vitest-environment jsdom */
import React from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { messages } from "@/app/messages";
vi.mock("@/app/preferences", () => ({useI18n: () => (key: keyof typeof messages["zh-CN"]) => messages["zh-CN"][key]}));
import { SceneDopeSheet } from "./SceneDopeSheet";
import { makeObject } from "./sceneGraph";
import { stillFrame } from "./sceneTracks";
import type { SceneContent, SceneShot } from "@/api/domains/scenes";
const camera = makeObject("camera", {id: "cam", name: "主机位", track: [stillFrame(makeObject("camera"), 0), stillFrame(makeObject("camera"), 5)]});
const walker = makeObject("figure", {id: "walk", name: "路人", track: [stillFrame(makeObject("figure"), 2)]});
const idle = makeObject("box", {id: "idle", name: "静止方块"});
const content = {objects: [walker, camera, idle]} as unknown as SceneContent;
const shot: SceneShot = {id: "s", name: "镜头 1", duration: 10, aspect: "16:9", easing: "smooth", camera_id: "cam"};
function sheet(overrides: Partial<React.ComponentProps<typeof SceneDopeSheet>> = {}) {
  const props = {content, shot, time: 0, selectedId: null, playing: false, onSeek: vi.fn(), onSelect: vi.fn(), onInsert: vi.fn(), onDelete: vi.fn(), onMove: vi.fn(() => true), ...overrides};
  return {...render(<SceneDopeSheet {...props}/>), props};
}
it("所有物体常驻，只有显式筛选才隐藏空轨", () => {
  const {container} = sheet();
  expect([...container.querySelectorAll('.scene-dope-name span')].map(el => el.textContent)).toEqual(["主机位", "路人", "静止方块"]);
  fireEvent.click(screen.getByRole('button', {name: '仅动画'}));
  expect(screen.queryByRole('button', {name: /静止方块/})).toBeNull();
  fireEvent.click(screen.getByRole('button', {name: '仅动画'}));
  fireEvent.change(screen.getByRole('textbox', {name: '搜索物体'}), {target:{value:'静止'}});
  expect(container.querySelectorAll('.scene-dope-row')).toHaveLength(1);
});
it("插入关键帧明确作用于选中物体和当前时间", () => {
  const {props} = sheet({selectedId:'idle', time: 3});
  fireEvent.click(screen.getByRole('button', {name: '插入关键帧'}));
  expect(props.onInsert).toHaveBeenCalledWith('idle', 3);
});
it("关键帧精确选中而不是近似点击轨道，并可跨物体多选删除", () => {
  const {props} = sheet();
  fireEvent.click(screen.getByRole('button', {name:'主机位 · 5.00s'}));
  expect(props.onSeek).toHaveBeenLastCalledWith(5);
  fireEvent.click(screen.getByRole('button', {name:'路人 · 2.00s'}), {shiftKey:true});
  fireEvent.keyDown(screen.getByRole('group'), {key:'Delete'});
  expect(props.onDelete).toHaveBeenCalledWith([{id:'cam',time:5},{id:'walk',time:2}]);
});
it("帧编辑的 Delete 不传播给删除场景物体的快捷键", () => {
  sheet(); const globalDelete=vi.fn(); window.addEventListener('keydown',globalDelete);
  fireEvent.click(screen.getByRole('button', {name:'主机位 · 5.00s'}));
  fireEvent.keyDown(screen.getByRole('group'), {key:'Backspace'});
  expect(globalDelete).not.toHaveBeenCalled(); window.removeEventListener('keydown',globalDelete);
});
it("只改帧时刻，键盘按帧步进可以撤销的一次操作", () => {
  const {props}=sheet();
  fireEvent.click(screen.getByRole('button', {name:'路人 · 2.00s'}));
  fireEvent.keyDown(screen.getByRole('group'), {key:'ArrowRight',shiftKey:true});
  expect(props.onMove).toHaveBeenCalledWith([{id:'walk',time:2}],1/30);
});
it("拖动关键帧释放时只提交一次，不把点选变成时间偏移", () => {
  const {props}=sheet(); const key=screen.getByRole('button',{name:'路人 · 2.00s'});
  key.parentElement!.getBoundingClientRect=()=>({left:0,width:100,right:100,top:0,bottom:30,height:30,x:0,y:0,toJSON:()=>({})});
  fireEvent.pointerDown(key,{clientX:20,button:0,pointerId:1});
  fireEvent.pointerMove(window,{clientX:40,pointerId:1});
  expect(props.onMove).not.toHaveBeenCalled();
  fireEvent.pointerUp(window,{clientX:40,pointerId:1});
  expect(props.onMove).toHaveBeenCalledExactlyOnceWith([{id:'walk',time:2}],2);
});
it("缩短镜头不会把范围外的已有关键帧画到面板外", () => {
  const {container}=sheet({shot:{...shot,duration:1}});
  expect(screen.getByRole('slider').getAttribute('aria-valuemax')).toBe('5');
  expect(container.querySelector<HTMLElement>('[aria-label="主机位 · 5.00s"]')!.style.left).toBe('100%');
});
it("零时长不会生成 NaN 坐标", () => {
  const {container}=sheet({shot:{...shot,duration:0},content:{objects:[idle]} as SceneContent});
  expect(container.querySelector<HTMLElement>('.scene-dope-playhead')!.style.left).toBe('0%');
});

it("Escape 取消正在拖动的关键帧，不提交移动", () => {
  const {props}=sheet(); const key=screen.getByRole('button',{name:'路人 · 2.00s'});
  key.parentElement!.getBoundingClientRect=()=>({left:0,width:100,right:100,top:0,bottom:30,height:30,x:0,y:0,toJSON:()=>({})});
  fireEvent.pointerDown(key,{clientX:20,button:0,pointerId:1});
  fireEvent.pointerMove(window,{clientX:40,pointerId:1});
  fireEvent.keyDown(screen.getByRole('group'), {key:'Escape'});
  fireEvent.pointerUp(window,{clientX:40,pointerId:1});
  expect(props.onMove).not.toHaveBeenCalled();
});
