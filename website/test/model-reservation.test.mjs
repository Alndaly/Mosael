import assert from "node:assert/strict";
import test from "node:test";

import {
  DEFAULT_RESERVATION_ROWS,
  reservationFromRows,
  rowsFromCapability,
} from "../src/components/admin/model-reservation.ts";

test("新异步任务默认预留一张图片", () => {
  assert.deepEqual(rowsFromCapability({}), DEFAULT_RESERVATION_ROWS);
});

test("已有模型的图片、视频和自定义计量都能回到表单", () => {
  const rows = rowsFromCapability({ reservation: { image: 1, second: 5, render: 2 } });
  assert.deepEqual(rows, [
    { unit: "image", amount: "1" },
    { unit: "second", amount: "5" },
    { unit: "render", amount: "2" },
  ]);
  assert.deepEqual(reservationFromRows(rows), { image: 1, second: 5, render: 2 });
});

test("空单位、非正整数与重复单位不会生成含混的能力声明", () => {
  assert.throws(() => reservationFromRows([]));
  assert.throws(() => reservationFromRows([{ unit: "", amount: "1" }]));
  assert.throws(() => reservationFromRows([{ unit: "image", amount: "0" }]));
  assert.throws(() => reservationFromRows([{ unit: "image", amount: "1.5" }]));
  assert.throws(() => reservationFromRows([
    { unit: "image", amount: "1" },
    { unit: " image ", amount: "2" },
  ]));
});
