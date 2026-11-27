# bohrium-pdf-skill

Bohrium「阅读01｜文献文档解析」参赛作品（挑战 `product-arena-08-3027d350`）。

## 作品是什么

一个可被 Agent 调用的 Skill：**从带文字层的双栏/多栏科研 PDF 中恢复正确阅读顺序，并为每段文字保留页码与区块坐标**，使解析结论可以回到原文核对。

聚焦题目指定的方向之一：**多栏阅读顺序与文字提取**。不追求做一个"大而全的 PDF 解析器"，不包含 OCR、表格行列还原与公式结构识别。

## 目录

```
SKILL.md                 技能定义（frontmatter + 调用方式/输入输出/异常/证据定位）
scripts/read_columns.py  唯一运行脚本，PyMuPDF，无网络依赖
references/
  output-schema.md       输出 JSON 完整字段与示例
  layout-method.md       版面判定算法、阈值、调参、已知伪影
使用与方法说明.md          完整使用步骤、方法、限制、失败处理、自查
GITHUB_URL.txt           本仓库链接
```

## 快速开始

```bash
python -m pip install pymupdf
python scripts/read_columns.py \
  --pdf paper.pdf \
  --out reading_order.json \
  --case-id case-01 \
  --md reading_order.md
```

输出 `reading_order.json` 的关键字段：`status`、`layout.page_columns`、`units[]`（含 `page`、`column`、`bbox_norm`、`unit_id`）、`excluded[]`、`warnings[]`、`uncertainty[]`。

## 方法要点

不用"找中间空白"的朴素做法（通栏标题会把栏缝糊死），改用 x 方向 1pt 窄条的**覆盖计数**识别栏缝：计数不超过峰值 40%、宽度不小于页宽 2%、左右两侧各至少 3 个块才认定。跨栏块作为分段边界，段内先左栏后右栏、栏内自上而下。页眉页脚按页高 7.5% / 92.5% 两条带隔离。

## 已验证

- 合成版式回归：3 页（通栏标题+双栏 / 跨栏图注+双栏 / 单栏），栏数识别 `2/2/1`，阅读顺序正确，单栏页不误切。
- 真实论文：arXiv 1512.03385（ResNet，12 页），`status=success`，11 页识别双栏、单栏参考文献页识别单栏，535 个文本单元。
- 确定性：连续两次运行，`unit_id` 与 `bbox_norm` 完全一致。

## 已知限制

图内文字（坐标轴刻度、图例）会作为正文块被抽出，可能排在图注之前；边注与水印可能被判为正文；不支持竖排与右向左版面；扫描件返回 `partial`/`unreadable`，不做 OCR 猜补。

## 许可

MIT
