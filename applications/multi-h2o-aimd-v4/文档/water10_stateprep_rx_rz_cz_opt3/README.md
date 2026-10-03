# 最新版：可训练参数符号图

按本次要求，优先使用 `water10_stateprep_symbolic_rx_rz_cz_opt3.svg` / `.png`。30条线路仍为单幅连续超长横图，不折行。可训练参数保留为 θ1–θ48，同一共享参数在不同门中使用同一编号；原有缩放/组合权重保留，例如 `RX(0.55·θ1)`。固定编码角、基变换常数仍显示数值，不能将所有旋转门一律改成独立参数。

从原始逐门清单恢复符号参数后，重新执行 RX/RZ/CZ、optimization_level=3、approximation_degree=1.0 编译。没有将旧数值图的门任意改名。符号化限制部分数值优化，因此新版共781门（343 RX、250 RZ、188 CZ），深度304；图片60997×1752像素。显示系数取5位有效数字，QPY和门清单保留完整表达式。

- `.qpy`：符号化编译电路，48个未绑定参数，执行前需赋值。
- `.logical.qpy`：符号化编译前线路。
- `.parameters.json`：theta编号、原始训练参数key、共享实例数及第6轮参考值。
- `.bound.qpy`：将48个参数绑定回当前第6轮检查点后的可执行线路。
- `.drawio`：原生可编辑图；`.svg`：可编辑文字与矢量门；`.png`：完整横图。
- `water10_stateprep_symbolic_source.py`：生成源码；`water10_stateprep_symbolic_verify.py`：数值核验源码。

已确认符号原线路绑定后与冻结原QPY完全相同。编译后绑定回检查点，使用全部连通分量的精确算符验证，最大元素误差约8.15e-15；状态保真度在浮点舍入精度内为1。严格1e-10检查通过，结果见符号版 `.verification.json`。旧数值图及实验记录已于2026-09-23清理。最新图的输入位于 `models/final/circuit_source/`，模型位于 `models/final/best_model.json`。

