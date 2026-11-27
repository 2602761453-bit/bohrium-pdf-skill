# 输出 JSON 完整字段

顶层结构（`reading_order.json`）：

| 路径 | 类型 | 说明 |
|---|---|---|
| `case_id` | string \| null | 传入的案例标识 |
| `skill` | string | 固定 `pdf-column-reader` |
| `source.path` | string | 输入 PDF 路径 |
| `source.sha256` | string | 输入文件 SHA-256，用于证明解析对象 |
| `source.pages` | int | 页数 |
| `source.bytes` | int | 文件字节数 |
| `status` | string | `success` / `partial` / `unreadable` |
| `layout.header_band` | float | 页眉判定比例（0.075） |
| `layout.footer_band` | float | 页脚判定比例（0.925） |
| `layout.max_columns` | int | 最大栏数（3） |
| `layout.page_columns` | object | 页码字符串到栏数的映射 |
| `pages[]` | array | 每页汇总，见下 |
| `units[]` | array | 文本单元，正文按阅读顺序 |
| `excluded[]` | array | 页眉页脚块 |
| `warnings[]` | string[] | 可继续但需告知的问题 |
| `uncertainty[]` | string[] | 未覆盖的部分 |
| `reading_order_text` | string | 正文按顺序拼接 |

`pages[]` 每项：

| 字段 | 类型 | 说明 |
|---|---|---|
| `page` | int | 页码，1 起算 |
| `size` | [float, float] | 页宽、页高（pt） |
| `columns` | int | 本页检测栏数，0 表示无文字层 |
| `body_blocks` | int | 参与排序的正文块数 |
| `furniture_blocks` | int | 页眉页脚块数（仅在有文字层的页） |
| `text_chars` | int | 正文字符数 |
| `note` | string | 仅无文字层页出现：`no usable text layer` |

`units[]` 每项：

| 字段 | 类型 | 说明 |
|---|---|---|
| `unit_id` | string | 稳定编号：`p{页}-c{栏}-o{序号}`；页眉页脚为 `p{页}-f-{序号}` |
| `page` | int | 页码，1 起算 |
| `column` | int | 栏序号，0 起；-1 表示跨栏或页眉页脚 |
| `column_kind` | string | `column` / `spanning` / `furniture` |
| `order` | int \| null | 全局阅读序号，正文从 1 递增；页眉页脚为 null |
| `role` | string | `body` / `header` / `footer` |
| `text` | string | 原文文字，保留原始换行，不做断词修补 |
| `bbox_norm` | [float×4] | `[x0, y0, x1, y1]`，按页宽高归一化到 0–1，左上为原点 |

## 示例（合成样本，非正式案例结果）

下面是 `--case-id synthetic-2col` 的节选，仅用于说明字段形状：

```json
{
  "case_id": "synthetic-2col",
  "skill": "pdf-column-reader",
  "source": {
    "path": "synthetic-2col.pdf",
    "sha256": "41714e4c2525...",
    "pages": 3,
    "bytes": 6455
  },
  "status": "success",
  "layout": {
    "header_band": 0.075,
    "footer_band": 0.925,
    "max_columns": 3,
    "page_columns": { "1": 2, "2": 2, "3": 1 }
  },
  "pages": [
    { "page": 1, "size": [595.0, 842.0], "columns": 2, "body_blocks": 11,
      "furniture_blocks": 2, "text_chars": 557 }
  ],
  "units": [
    {
      "unit_id": "p1-c-1-o0001",
      "page": 1,
      "column": -1,
      "column_kind": "spanning",
      "order": 1,
      "role": "body",
      "text": "A Two Column Paper About Reading Order",
      "bbox_norm": [0.1176, 0.1102, 0.6348, 0.1363]
    },
    {
      "unit_id": "p1-c0-o0004",
      "page": 1,
      "column": 0,
      "column_kind": "column",
      "order": 4,
      "role": "body",
      "text": "LEFT-1 alpha beta gamma delta epsilon zeta eta theta.",
      "bbox_norm": [0.1008, 0.2379, 0.4699, 0.2526]
    }
  ],
  "excluded": [
    { "page": 1, "role": "header", "text": "Journal of Reproducible Layouts 12 (2026) 1-3" },
    { "page": 1, "role": "footer", "text": "1" }
  ],
  "warnings": [],
  "uncertainty": [],
  "reading_order_text": "A Two Column Paper About Reading Order\n..."
}
```

## 映射到平台的 result.json

参赛运行契约要求 `result.json` 含 `case_id`、主结果、证据、状态与不确定性。建议映射：

| result.json 字段 | 来源 |
|---|---|
| `case_id` | 平台 `case.json` 的 id，不要用 `--case-id` 覆盖它 |
| 主结果 | `reading_order_text`，或按答案需求从 `units[]` 摘取 |
| 证据 | 每个被引用的 `unit_id` + `page` + `column` + `bbox_norm` |
| 状态 | `status` 直接映射：success → success，partial → partial，unreadable → failed |
| 不确定性 | `warnings` + `uncertainty` 原样并入 |

不要把 `reading_order_text` 当作"全文已完整"的证据：图内文字、边注仍在其中。
