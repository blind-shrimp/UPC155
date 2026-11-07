# UPC B题：数据获取渠道与联系邮件

检索日期：2026-11-07。状态：已下载ISSIA-3D标注并做初步字段检查；尚未向任何作者发送邮件。

## 1. 优先级与获取路径

### A. ISSIA-3D：立即检查的公开数据

- [作者官方仓库](https://github.com/mguti97/SoccerNet-v3D)
- [CSV下载](https://github.com/mguti97/SoccerNet-v3D/releases/download/v1.0.0/ISSIA-3D.csv)
- [已下载的本地CSV](C:/Users/pc/Documents/ChatGPT/upc/data_sources/ISSIA-3D.csv)

提供多相机三角测量得到的球三维位置（米）、帧号、参与相机和重投影误差。初步检查：2465行，其中1689行包含可解析的三维坐标；按有效帧连续性分为79段，最长122帧。这些段不等于79次踢球，也不表示已有79条可用空中轨迹。

下一步：核实帧率、坐标方向、缺失值及误差，识别无接触的空中飞行段；检查是否包含射门或点球。原数据的相机划分用于视觉任务，不应直接沿用为本研究的踢球样本划分。同一次运动在不同相机下必须归入同一数据集合。

注意：该项目的SoccerNet-v3D部分与ISSIA-3D不同，论文明确强调后者具有时间信息。当前应优先处理ISSIA-3D。

作者：Marc Gutiérrez Pérez。研究所公开目录所列邮箱：`mgutierrez@iri.upc.edu`。

[邮箱来源：研究所人员目录](https://www.iri.csic.es/staff)

### B. ball3d：最值得联系的现成轨迹资源

- [官方项目与作者邮箱](https://github.com/lukaszgrad/ball3d)
- [数据格式、许可与下载入口](https://github.com/lukaszgrad/ball3d/blob/main/DATA.md)
- [作者提供的Google Drive目录](https://drive.google.com/drive/folders/1QCrmzZYZt9_tIBqY6AmP7DjDyPXe3AuI)

项目提供比赛与训练场景数据、三角测量三维参考轨迹、分段标注和模型预测。优先申请或下载：`ball_3d-gt.csv`、`ball_pivot_point-gt.csv`、`sequence_metadata.json`。位置单位是分米，需要除以10转为米。

不要把`ball_3d.<version>.csv`模型输出当真实标签。三角测量参考数据也有重建误差，应询问是否使用物理拟合或全轨迹平滑，以判断独立验证的强度。

数据文档明确提供学术访问联系邮箱：**Łukasz Grad，`l.grad@mimuw.edu.pl`**。标注采用CC-BY-NC-SA-4.0；视频有单独使用限制。尚未验证Drive目录的实际下载权限，也未确认包含多少点球。

### C. IDSSE / Sportec：备选比赛追踪数据

- [原始数据DOI](https://doi.org/10.6084/m9.figshare.28196177)
- [PySport镜像及加载说明](https://huggingface.co/datasets/pysport/idsse-data)
- [关联论文](https://doi.org/10.1038/s41597-025-04505-y)

镜像说明包含7场比赛、25 fps追踪、同步事件和场地信息。适合通过射门事件筛选片段。当前尚未检查实际文件的球高度字段及其质量，不能先认定适合三维空气动力学校准。

25 fps的间隔为0.04秒，不直接对应0.05秒和0.10秒；插值及离脚时刻误差需要单独评估。

### D. 足球空气动力学论文作者：申请现有实验轨迹

[Creating drag and lift curves from soccer trajectories](https://shura.shu.ac.uk/15728/1/Kelley%20-%20Creating%20drag%20and%20lift%20curves%20%28AM%29.pdf)报道了29条轨迹分析，是实验数据申请线索。本次全文访问被站点保护阻止，尚未确认是否有公开原始数据、三维完整性或现行联系人。

可申请已有位置时间序列、旋转记录和实验条件；不要求作者重新实验或为本题拟合参数。论文中的系数曲线可作为参数依据，但不能代替独立轨迹验证。

## 2. 推荐行动

1. 立即检查已下载ISSIA-3D，判断能否得到连续、质量足够的空中轨迹。
2. 优先联系ball3d作者，请求现有小样本及访问权限；无需先下载整场视频。
3. 核查IDSSE实际球高度字段，满足要求后再考虑扩大下载。
4. 不必限定所有校准数据都是点球：无接触自由飞行段可帮助校准动力学，但点球预测的准确性仍需任务匹配的独立测试。
5. 不将任意比赛片段平移、改时间零点后声称为真实11米点球；保持来源和测试情景标签。

## 3. 给ball3d作者的英文邮件草稿

**To:** l.grad@mimuw.edu.pl  
**Subject:** Request for access to existing 3D soccer-ball trajectory data

Dear Dr. Grad,

We are an undergraduate team participating in the University Physics Competition. We are studying the prediction of a soccer ball's goal-plane crossing position from two early 3D observations, including prediction uncertainty.

We found your ball3d project and its data documentation. We would like to request access to existing triangulated 3D trajectories for non-commercial academic use. We are not requesting new experiments, custom data processing, or assistance with solving the competition problem.

Could you please point us to an existing downloadable subset containing uninterrupted airborne ball trajectories, together with frame timing and contact annotations? A small sample of the existing ball_3d-gt.csv, ball_pivot_point-gt.csv, and sequence_metadata.json files would be very helpful. Penalty kicks or shots would be particularly relevant, but other free-flight segments may also help us evaluate a physical simulator.

If already documented, we would appreciate a link describing reconstruction accuracy and whether the reference coordinates are smoothed or constrained by a fitted physical trajectory. We will follow the applicable license and cite your work.

Thank you for your time.

Best regards,
[Your name]
[University / team]
[Email]

## 4. 给ISSIA-3D作者的英文邮件草稿

**To:** mgutierrez@iri.upc.edu  
**Subject:** Existing ISSIA-3D trajectory data and timing documentation

Dear Marc Gutiérrez Pérez,

We are an undergraduate team participating in the University Physics Competition. We have downloaded the ISSIA-3D.csv annotations from your SoccerNet-v3D repository for a study of early ball-flight prediction.

Could you please point us to existing documentation for the frame rate, coordinate conventions, and available annotations of kick/contact times or shot segments? We would also appreciate any existing information about the accuracy of the triangulated ball coordinates and whether temporal smoothing is applied.

We are requesting only access to existing data or documentation, not new measurements, custom processing, or assistance with the competition solution. We will respect the data-use terms and cite your paper.

Thank you very much.

Best regards,
[Your name]
[University / team]
[Email]

## 5. 联系状态

已核实公开联系线索并备好草稿，但当前没有连接邮箱工具，未发送邮件。草稿中的署名需要替换为真实信息。现有数据访问申请与委托他人新增研究工作是不同事项；这里仅申请已有数据与已有文档。
