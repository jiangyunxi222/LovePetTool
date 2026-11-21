# BandoriLovePet 手机角色包协议 v1

协议标识为 `bandorilovepet-role`，版本为整数 `1`。Windows 制作工具生成协议包，Android LovePet 读取协议包并使用自己的角色工作台。ZIP、LPK 和 WPK 共用同一套角色目录、模型及素材。

## 准备素材目录

素材整理完成后，将整个目录交给制作工具，也可将它压为一个素材 ZIP 后交给工具转换。文件名和目录都是确定的输入。素材整理阶段可以人工处理，也可以用 AI 协助标注。Windows 工具按规则识别和校验，不需要网络或 AI。

```text
MyRole/
  role.json
  renames.json                         可选
  001__常服.model3.json
  002__舞台服.model3.json
  assets/
    models/anon.moc3
    textures/anon_00.png
    physics/anon.physics3.json
    idle/anon_idle.motion3.json
    motions/001/010__点头__body-left.motion3.json
    motions/002/010__拨弦__body.motion3.json
    expressions/001/020__微笑.exp3.json
    voices/001__演出前的问候.wav
    voices/001__演出前的问候.txt
  runtime/live2dcubismcore.min.js       也可在工具中指定集中目录
```

- `role.json` 提供稳定 `id`、显示 `name`、来源 `game` 和分组 `group`。`id` 为 1–80 位 ASCII 字母、数字、下划线或短横线。换名字时保留原 ID。
- 衣装文件位于根目录，按 `三位编号__显示名.model3.json` 命名。Cubism 2 使用 `.model.json`。模型文件中的网格、贴图、物理、姿势和待机引用以素材目录为起点，实际资源放在 `assets/`。
- 动作放在 `assets/motions/<衣装三位编号>/`。文件名为 `三位编号__显示名[__触发区域].motion3.json`，Cubism 2 使用 `.mtn`。区域可用 `body`、`left`、`right`，多选用 `-` 连接。省略区域时，该动作可从列表播放。命名 `010__点头__body-left.motion3.json` 会生成一条「点头」，可由上身和左臂触发。
- 表情放在 `assets/expressions/<衣装三位编号>/`，按 `三位编号__显示名.exp3.json` 命名。Cubism 2 使用 `.exp.json`。
- 语音放在 `assets/voices/`，按 `三位编号__显示名.wav` 等规则命名。支持 WAV、MP3、OGG、M4A、FLAC。每条配同名 UTF-8 `.txt`，内容作为字幕。`.txt` 会写入目录索引。
- 网格使用 `.moc3` 或 `.moc`，贴图支持 PNG、JPG、JPEG、WebP。物理和姿势使用 JSON。附加运行库需从已有、获授权的兼容角色包准备。Cubism 3 需要 `live2dcubismcore.min.js`。含 Cubism 2 衣装时同时需要 `live2d.min.js`。工具和 LovePet 都校验已支持版本的 SHA-256。
- 每个列表的编号和展示名需唯一。为不同动作写实际差异，例如「向角色左侧拨弦」和「向角色右侧拨弦」。同一动作有多个触发区时，在同一个文件名里声明区域。用于资源定位的编号可以放在文件名前缀或索引 `id` 中。
- 如果素材整理时移动或改名，可直接更新模型 JSON，或附 UTF-8 的 `renames.json`，记录旧相对路径到新 `assets/` 路径的映射。挂接依赖原文件引用，工具会核对换名后每个引用能找到实际文件。

`role.json` 示例

```json
{
  "id": "example-role",
  "name": "示例角色",
  "game": "OurNotes",
  "group": "示例乐队",
  "hitRegions": {
    "001": {
      "body": [-0.4, -0.8, 0.4, -0.2],
      "expression": [-0.3, -0.2, 0.3, 0.2]
    }
  }
}
```

`hitRegions` 可省略。这里的坐标仅用于示范字段结构，实际制作填入模型自身坐标中的 `[xmin, ymin, xmax, ymax]`。合法区域名有 `body`、`left`、`right`、`expression`、`voice`、`wardrobe`、`menu`。Cubism 3 使用模型单位，以模型原点及 `PixelsPerUnit` 换算。Cubism 2 使用模型内部坐标。这些值与屏幕分辨率无关。

`renames.json` 示例

```json
{
  "textures/texture_00.png": "assets/textures/anon_00.png",
  "model.moc3": "assets/models/anon.moc3"
}
```

## 工具输出和 LovePet 读取

| 文件 | 内容 |
| --- | --- |
| `manifest.json` | 根目录中的 UTF-8 JSON，包含 `format`、`version` 和 `files_sha256`。哈希表逐个列出清单本身以外的所有文件。 |
| `catalog.json` | 单角色目录。来源 `game`、`group`、角色 `id`、`name`、可选 `motionFadePolicy`，以及 `costumes`、`voices` 两个数组。 |
| `*.model.json` / `*.model3.json` | 每件衣装的 Live2D 模型配置。保留网格、贴图、可选物理及姿势、待机动作和声明式口型设置。 |
| `assets/` | 模型和目录实际引用的媒体资源。路径以 `/` 分隔，覆盖衣装资源以及动作、表情和语音。 |
| `runtime/` | 已支持的 Live2D 官方渲染内核。APK 提供角色工作台和其余播放器逻辑。 |

`catalog.json` 的字段

| 记录 | 字段 |
| --- | --- |
| 衣装 | `id`、`name`、`flag`、`file`、布尔值 `cubism3`、`actions`、`expressions`。可选 `hitRegions`。 |
| 动作 | `id`、`name`、`flag`、`file`、`categories`。时长 `duration` 为秒，`fadeIn` 和 `fadeOut` 为毫秒。有 `motionFadePolicy: "source"` 时应用来源淡入淡出。 |
| 表情 | `id`、`name`、`flag`、`file`。空 `file` 表示恢复默认表情。 |
| 语音 | `id`、`name`、`flag`、`file`、`caption`。可选 `costumeIds` 限定可用于演出的衣装。 |

各 `id` 都是非负 32 位整数，在所属数组内唯一。`flag` 用于收藏和演出，在所属数组内唯一，为 1–128 位 ASCII 字母、数字、下划线或短横线。迁移合并旧条目时，可用 `aliasFlags` 保留此前的标识。完全相同的衣装合并时，`aliasIds` 保留旧衣装编号。工作台使用 `name` 展示，切换语言或改显示名时保留 `id` 和 `flag`。

ZIP 将上述文件直接放在根目录。LPK 采用未加密 `STD2_0` 容器，在根目录额外放 `config.mlve`，并将其列入 `files_sha256`。WPK 在外层使用 `config.json` 声明内嵌 `.lpk` 的 `lpkFile`，角色和协议清单位于这份 LPK 内。LovePet 先识别角色清单，再验证哈希、模型引用、字段和运行库，最后打开同一个自带工作台。原版第三方 LPK、WPK 可以继续用其原有导入路径。

包文件和展开后的数据均不超过 2 GB，最多 20,000 个文件。单个模型或索引 JSON 不超过 12 MiB。路径使用相对路径，禁止重复路径、父目录引用、Windows 设备名和路径转义。包内文件名必须与清单一致。模型名称、字幕和素材一律按数据处理。桌面控制台、ViewerEX 控制脚本、安装器、网络前端和程序文件不属于协议内容。

## 转换边界

- 三种协议包可以互转，角色目录及所有工作台条目一并保留。不同容器会更新清单。
- BandoriLove 旧版发行 ZIP 依据旧索引整理为协议包。相同播放素材的重复入口保留触发区域和收藏别名。不同素材同名时使用可核实的触发区域、源文件标识或实际时长区分。
- 第三方 LPK、WPK 依据声明式模型、动作、表情及音频数据转换。源包含专有脚本、加密创意工坊配置或独立联动场景时，需要对应的源配置。第三方无文本的语音会明确标记缺少字幕。转换只使用能够读取的数据，缺失的显示描述、交互区域可从管理素材的原始文件补充。
