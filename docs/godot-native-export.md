# Godot 原生 2D 导出

已实现第一版：把 Spine 4.2 的刚性切片角色导出为 `Skeleton2D` / `Bone2D` /
`Sprite2D` 和 `AnimationPlayer`。输出不依赖 Spine runtime，可以在 Godot 中继续编辑。
资源面向 Godot 4；目前实际验证版本为 **Godot 4.7.2**。

## 在应用中使用

1. 打开角色；可以先通过 Codex workflow 生成并导入新皮肤。
2. 点击 **Export → Godot 4 · native cutout**，选择皮肤。
3. 导出后复制 `project.godot` 路径，在 Godot 项目管理器导入并运行。
4. 示例窗口的菜单可以切换动作和皮肤。

每次创建 `<角色目录>/.genie/exports/godot/<id>/`，不会覆盖之前的 Godot 工程。
导出包含源 JSON 中的皮肤，以及选中的已打包生成皮肤；恢复任务不影响原资源。
网页中的已保存部件变换、当前显隐状态会带入导出。选择当前显示的皮肤时，
还会应用颜色／图像编辑面板中待导出的修改。其他皮肤不会套用当前皮肤的待导出修改。
只有工作目录、尚无配套 JSON 和 atlas 的皮肤，需要先完成生成／重新打包。

网页预览仍是 Spine 预览。Godot 导出是实际的原生资源，不是网页截图或帧序列。

## 命令行

从仓库根目录运行，依赖后端环境中的 Pillow；PMA 图集还使用 NumPy：

```powershell
.venv/Scripts/python.exe scripts/export_godot.py --spine examples/sombrero/sombrero.json --output .genie/godot/sombrero
```

`sombrero.json` 是完整美术角色，有 idle；`skeleton.json` 是另一份简化切片角色，
包含 idle、walk、run、wave、jump、attack 六套预设。不要混用两者的图集。

```powershell
.venv/Scripts/python.exe scripts/export_godot.py --spine examples/sombrero/skeleton.json --output .genie/godot/six-actions
```

其他参数：

| 参数 | 用途 |
| --- | --- |
| `--check` | 只检查骨架／动画能力，输出不支持项；不会检查贴图是否完整 |
| `--atlas path` | 指定原图集；默认使用 JSON 同名 `.atlas` |
| `--skin-json path` | 添加同一骨架的生成皮肤，可重复传入；各自使用同名 `.atlas` |
| `--skin name` | 默认显示的皮肤，默认 `default` |
| `--fps 60` | 曲线采样率，范围 12–120；默认 60 |
| `--loops idle,walk,run` | 完整指定循环动作；空字符串表示都不循环 |

导出目录必须不存在。退出码 0 表示成功；检查到不支持项时 `--check` 返回 2，
导出失败返回 1。应用接口是 `POST /api/export/godot`：

```json
{"skin_name": "default", "edits": {}, "hidden": [], "fps": 60}
```

成功响应包含 `project`、`scene`、`output_dir`、动画与皮肤清单。
无法保留的特性返回 HTTP 422，`detail.unsupported` 列出具体骨骼／动画／附件。

## 输出与游戏接入

```text
project.godot        可独立运行的演示工程
demo.tscn / demo.gd  动作、皮肤选择菜单
character.tscn      原生骨架与切片场景
character.gd        换肤、播放、显隐辅助方法
animations.tres    可编辑的 AnimationLibrary
textures/           已还原图集旋转和裁边的独立 PNG
character.json      通用角色数据：Y 向上、像素、角度；动画为绝对值采样轨道
import_report.json 导出清单及限制
```

接入现有游戏时，把 `character.tscn`、`character.gd`、`animations.tres` 和
`textures/` 一起复制到同一个新目录，再实例化场景。资源引用是相对路径。
**不要用演示的 `project.godot` 覆盖游戏配置。**

```gdscript
@onready var character = $Character

func _ready():
    character.play_animation("walk")
    # 如果有这个皮肤：character.set_skin("emerald")
    # character.set_part_visible("hat", false)
    # character.reset_pose()
```

`play_animation` 默认交叉混合 0.15 秒，也可以传入 0 直接切换。
每套动画都会给未参与运动的骨骼属性写入初始值，避免攻击后的姿势残留到 idle。
可以继续在 Godot 中配置 AnimationTree；此版没有自动生成游戏状态机、碰撞和移动逻辑。

## 支持范围

| 内容 | 当前行为 |
| --- | --- |
| 骨骼层级、初始位移／旋转／缩放、镜像 | 支持普通继承；转换 Y 轴和角度方向 |
| region 附件、附件位移／旋转／缩放、颜色与静态顺序 | 支持；各切片使用独立绘制层级 |
| 皮肤 | 支持每 slot 一个静态附件；缺少的覆盖回退到 default |
| atlas | 支持 `xy/size/orig/offset` 与 `bounds/offsets`、多页、90° 倍数旋转、裁边、PMA |
| 骨骼动画 | 支持 rotate、translate、scale 及单轴变体；保留初始姿态偏移与缩放乘法语义 |
| 曲线 | 支持线性、阶跃、Spine 4.2 每通道贝塞尔；采样后使用 Godot 属性轨道 |
| 六套预设 | 导出输入中已有的动作，不凭空添加输入没有的动作 |
| 循环 | 默认 idle/walk/run 循环，其他一次性；可显式覆盖 |

当前会拒绝：网格／权重／deform、clipping、序列附件、每 slot 多附件、
IK／transform／path／physics 约束、特殊骨骼继承与剪切、非普通混合／双色着色、
动态 slot 轨道、动态绘制顺序和事件。没有“忽略不支持项继续导出”的开关。
这属于转换器首版范围，不表示 Godot 没有对应能力。

贝塞尔转成采样轨道，所以输出可编辑，但不是原来的稀疏控制点。
默认 60 Hz 不是任意复杂曲线的无损保证；快速或细微动作可以改用 120 Hz 并检查。
此版也不负责从任意 Godot `.tscn` 反向导入应用。

## 验证

```powershell
$env:GODOT_BIN = 'C:/path/to/Godot_console.exe'
.venv/Scripts/python.exe -m pytest reskin-app/tests -q
```

引擎对照测试还需要 Node 和前端的 `npm ci`。未配置 Godot 时，仅跳过引擎测试，
Python 的导入、图集恢复、能力检测和 API 测试仍可运行。

测试用项目当前安装的官方 Spine runtime 求值，与真实 Godot 的骨骼矩阵比较，
覆盖非等比缩放、镜像、阶跃、延迟首帧、动作切换和六套预设。另检查皮肤切换、
透明边缘、旋转裁边恢复、输入不支持时拒绝导出和输出不被覆盖。

实际画面检查可在已导入的输出工程上执行：

```text
Godot_console.exe --path <输出目录> --script <仓库>/reskin-app/tests/render_godot.gd --rendering-method gl_compatibility
```

这一步需要图形环境，不能加 `--headless`；会在输出的 `qa/` 保存初始姿态、
动画开始／中点／末尾及所有皮肤的检查帧和清单。

格式依据：[Godot Bone2D](https://docs.godotengine.org/en/stable/classes/class_bone2d.html)、
[Godot Animation](https://docs.godotengine.org/en/stable/classes/class_animation.html)、
[Spine JSON](https://esotericsoftware.com/spine-json-format)、
[Spine Atlas](https://esotericsoftware.com/spine-atlas-format)。
