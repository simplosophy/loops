# HLP Realtime Control Plane（0.3 规范草案 · 已收敛）

| | |
|---|---|
| **日期** | 2026-07-13 |
| **状态** | **决策已收敛**；规范正文见 `docs/specs/HLP.md` 附录 C |
| **实现** | 本阶段 **不** 改 `loops/hlp` 状态机 / 不实现 voice·BCI |

## 已拍板决策

| ID | 决策 |
|----|------|
| D1 | Soft control **不** 进入 Task 状态机 |
| D2 | Soft 流合并在 host/channel/profile；HLP **只收** 合并后的 `task.amend` / hard 事件 |
| D3 | BCI 等 **默认不得** 单独 resolve 高风险 hard checkpoint |
| D4 | 不引入实时责任图；单 principal + 子 Task / ownership |
| 路线 | **先收敛规范**，mock promotion / voice 演示后置 |

## 架构（不变）

```text
Channel/Sensor → promotion → HLP responsibility → adapter → Harness
```

- Hard → checkpoint / interrupt  
- Soft → 合并后 `task.amend`（state 不变）  
- Principal = 人；传感器 ≠ 责任主体  

## Profiles

`HLP-batch` · `HLP-continuous`（0.2.0）· `HLP-industrial` · `HLP-realtime`（附录 C）

## 非目标

Media 一等对象、SFU/编解码、厂商 API 绑定、可编辑 audit 历史、soft=Review.approve。

## 落地顺序

| 阶段 | 状态 |
|------|------|
| 计划 + 附录 C 初稿 | 完成 |
| **决策收敛写进附录 C / §7.8–7.9 / conformance** | **本提交** |
| 0.3-reference（可选 ControlSignal + audit provenance 代码） | 未开始 |
| mock channel promotion 演示 | 后置 |

## 参考

- 规范：`docs/specs/HLP.md` 附录 C  
- 边界：`docs/architecture/OVERVIEW.md` 准实时小节  
