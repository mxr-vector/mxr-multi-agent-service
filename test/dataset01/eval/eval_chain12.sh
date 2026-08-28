#!/usr/bin/env bash
# 最新代码检索基准复测：native（无 wiki 基线）→ tool（wiki+多跳，生产语义）
R=/home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
cd /home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/eval
$PY longbench_v3_eval.py > $R/v3_baseline_v2.log 2>&1
echo "[chain12] baseline rc=$?" >> $R/eval_agent_chain.log
$PY longbench_wiki_eval.py --multihop-only-multihop > $R/v3_wiki_v2.log 2>&1
echo "[chain12] wiki-tool rc=$?" >> $R/eval_agent_chain.log
date > $R/EVAL_RETRIEVAL_V2_DONE
echo "[chain12] ALL DONE" >> $R/eval_agent_chain.log
