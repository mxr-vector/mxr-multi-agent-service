#!/usr/bin/env bash
R=../results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
# 1) 等补跑完成
while pgrep -f "longbench_wiki_eval[.]py --retry-failed" > /dev/null; do sleep 30; done
cp $R/longbench_v3_wiki_results.json $R/longbench_v3_wiki_forced_results.json
cp $R/longbench_v3_wiki_summary.json $R/longbench_v3_wiki_forced_summary.json
echo "[chain2] forced arm archived" >> $R/eval_chain2.log
# 2) 生产语义臂：仅多跳题启用逐跳
$PY longbench_wiki_eval.py --multihop-only-multihop >> $R/v3_wiki_prod_semantics.log 2>&1
cp $R/longbench_v3_wiki_results.json $R/longbench_v3_wiki_prod_results.json
cp $R/longbench_v3_wiki_summary.json $R/longbench_v3_wiki_prod_summary.json
date > $R/EVAL_CHAIN2_DONE
echo "[chain2] ALL DONE" >> $R/eval_chain2.log
