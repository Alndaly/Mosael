/**
 * 字段与输出的**软数据类型**。节点表单(给不给素材选择器)和工作流的就绪检查(连线类型对不对得上)
 * 读的是同一份,所以它住在表单这一层,而不是某个宿主里。
 */

/** 软数据类型:仅用于就绪检查提示,不阻断运行(模板终究是字符串插值)。 */
export type DataType = "text" | "asset" | "sequence" | "number" | "json" | "any";

const DATA_TYPES = new Set<DataType>(["text", "asset", "sequence", "number", "json", "any"]);

export function normalizeDataType(value: unknown): DataType {
  const declared = String(value ?? "").trim() as DataType;
  return DATA_TYPES.has(declared) ? declared : "any";
}

/**
 * 一个输入字段**装的是什么** —— 素材?时间线?还是随便什么值。
 *
 * **权威在后端**:节点声明里每个配置字段带着 `data_type`(见 domain/workflows.config_data_type,
 * 按 asset_id / sequence_id 这套命名自动推)。这里只负责读。
 *
 * 此前这是前端自己抄的一张表,后果是三件事一起坏:「素材」节点本身就漏了(它整个存在的意义
 * 就是指向一份素材,却拿不到素材选择器,用户只能手打一串十六进制)、asset_tag / asset_update /
 * browser_upload 也漏了、而**插件节点永远不可能被那张表覆盖** —— 它们是运行时才知道的。
 * 加一种节点忘了补表不会报错,只是安静地少了选择器和类型校验。
 */
export function fieldDataType(spec: object | null | undefined): DataType {
  return normalizeDataType((spec as { data_type?: unknown } | null | undefined)?.data_type);
}
