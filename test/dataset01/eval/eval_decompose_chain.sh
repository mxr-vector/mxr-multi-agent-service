#!/usr/bin/env bash
R=../results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
# 1) 对照臂：当前终态（双塔+席位5，无分解）
$PY longbench_wiki_eval.py --multihop-only-multihop >> $R/v3_wiki_decompose_control.log 2>&1
cp $R/longbench_v3_wiki_results.json $R/longbench_v3_wiki_decompose_control_results.json
cp $R/longbench_v3_wiki_summary.json $R/longbench_v3_wiki_decompose_control_summary.json
cp $R/longbench_v3_wiki_report.md $R/longbench_v3_wiki_decompose_control_report.md
echo "[chain] control done" >> $R/eval_decompose_chain.log
# 2) 分解臂：开关开启
MULTIHOP_DECOMPOSE_ENABLED=true $PY longbench_wiki_eval.py --multihop-only-multihop >> $R/v3_wiki_decompose_arm.log 2>&1
cp $R/longbench_v3_wiki_results.json $R/longbench_v3_wiki_decompose_arm_results.json
cp $R/longbench_v3_wiki_summary.json $R/longbench_v3_wiki_decompose_arm_summary.json
cp $R/longbench_v3_wiki_report.md $R/longbench_v3_wiki_decompose_arm_report.md
date > $R/EVAL_DECOMPOSE_DONE
echo "[chain] ALL DONE" >> $R/eval_decompose_chain.log
