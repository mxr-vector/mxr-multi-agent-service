#!/usr/bin/env bash
R=/home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
cd /home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/eval
# 等对照臂 + 关系构建都结束，再起工具臂（吃满索引覆盖，避免网关争抢）
while pgrep -f "longbench_agent_eval[.]py --no-agent-tools" > /dev/null; do sleep 120; done
echo "[chain3] control done" >> $R/eval_agent_chain.log
while pgrep -f "build_relation_index[.]py" > /dev/null; do sleep 300; done
echo "[chain3] relation build done" >> $R/eval_agent_chain.log
$PY longbench_agent_eval.py --out longbench_agent_tools_results.json >> $R/v3_agent_tools.log 2>&1
date > $R/EVAL_AGENT_DONE
echo "[chain3] ALL DONE" >> $R/eval_agent_chain.log
