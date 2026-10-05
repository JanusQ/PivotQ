# Twenty-water application scope

- Work only in this application unless the user explicitly changes scope.
- No training, optimization updates, checkpoint restoration, or physical QPU tests in this task.
- Keep `training_updates=0` and `model_status=initialized_untrained` in every execution record.
- Frozen water10 data and checkpoints are source references; never change or read them at runtime.
- Preserve 20 waters / 60 atoms / 60 qubits, 48 shared quantum parameters and 120 X/Z expectations.
- Keep one global circuit, encoding 1B→2B→3B then trainable 1B→2B→3B, with terminal measurements only.
- The current AIMD encoding is continuous, has no angle hard floor, and follows v4's bx/by orientation slot.
- CPU validation is exact complex128 tensor factors from actual connectivity. Never call it a dense 60-qubit statevector, MPS, or a hardware result.
- Real QPU deployment uses the reference HTTP protocol and an explicitly confirmed 60-qubit device profile. Never invent topology, readout labels, or capability evidence.
- Keep environments, MBX libraries and installation logs outside this directory. No copied framework, legacy data, training outputs or vendor source trees.
- Primary server mirror: `/home/hzhang/code/PivotQ/applications/60-qubit-circuit` on `109-32cpu`.
- Use `scripts/sync_server.py` and compare hashes after final edits; preserve compact reports and requested SVGs.
