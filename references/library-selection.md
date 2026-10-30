# S1 选型与库

范围到 Gerber：这里关心的是**器件电气与封装是否正确**，而不是下单成本。基础库/扩展库/换料费只在你另行做 SMT 下单时才有意义，仅作备注。

## 必做核对（G2 的依据）

1. **引脚数量与功能**：对照原厂 datasheet 逐脚核对符号。实测事故：系统库 Type-C 只有 8 脚、无 D+/D-（LB-02）。
2. **封装与实物**：封装名、焊盘尺寸、引脚 1 位置、极性。同封装不等于兼容替代料。
3. **关键值是否存在**：实测系统库搜不到 1.66kΩ，只能用 2kΩ 作安全替代并记录影响（该电阻决定充电芯片的充电电流）（LB-02）。
4. **阻容按型号搜**：系统库阻容按具体型号建（如 `0402WGF1002TCE`=10k 0402），没有通用 R/C；模糊搜索全是噪声（LB-01）。下表是实测可用的几个公开型号（均为立创基础库常见阻容，**仅作搜索关键字示例**，使用前请以你本机库实际搜索结果为准）：

| 值 | 封装 | 系统库型号 | 立创编号 |
|---|---|---|---|
| 10kΩ ±1% | 0402 | `0402WGF1002TCE` | C25744 |
| 4.7kΩ ±1% | 0402 | `0402WGF4701TCE` | C25900 |
| 100nF ±10% 50V | 0402 | `0402B104K500CT` | C152814 |
| 10uF ±10% 10V | 0805 | `0805B106K100NT` | C90544 |

5. **工艺可做性**：焊盘/孔径要符合所选工艺（如插件孔建议 ≥0.5mm、BGA 焊盘等，见 spec 库）。

## 相关 API

| 目的 | 接口 |
|---|---|
| 按关键字搜器件 | `eda.lib_Device.search(key, libraryUuid, classification, symbolType, itemsOfPage, page)` |
| 按立创编号取器件 | `eda.lib_Device.getByLcscIds(lcscIds, libraryUuid, allowMultiMatch)` |
| 系统库 UUID | `getAllLibrariesList()` **不含**系统库；系统库 UUID 用 `getSystemLibraryUuid()` 取得 |
| 放置原理图器件 | `eda.sch_PrimitiveComponent.create({libraryUuid, uuid}, x, y, subPartName, rotation, mirror, addIntoBom, addIntoPcb)`（x/y 单位 10mil） |

## 官方行为提醒

- 在 EDA 里**修改“值”属性会清空“供应商编号”**（官方文档明文），防止值与编号不对应；改值后须重新分配编号。
- 网表属性含 `Supplier` / `Supplier Part`（C 编号）/ `Manufacturer(Part)` / `JLCPCB Part Class` / `Add into BOM` / `Convert to PCB`。
- `ELIB_DeviceJlcLibraryCategory` 只有 `STANDARD`（基础）与 `EXTEND`（扩展）两个成员。

## 仅在做 SMT 时才用（备注）

换料费（官方 member.jlc.com，2026-10-30）：经济型 基础库 0 元 / 扩展库 20 元·种；标准型 基础与扩展均 8 元·种。BOM 若填了嘉立创编号，**以编号为准**，错误编号比没有编号更危险。这些属于下单阶段，不在本 skill 流程内。
