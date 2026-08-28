#!/usr/bin/env bash
R=../results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
# 1) 对照臂（不依赖关系索引，立即开跑；增量落盘防宕机丢失）
$PY longbench_agent_eval.py --no-agent-tools --out longbench_agent_control_results.json >> $R/v3_agent_control.log 2>&1
echo "[chain2] control done" >> $R/eval_agent_chain.log
# 2) 等关系索引构建完成（工具臂吃满索引覆盖）
while pgrep -f "build_relation_index[.]py" > /dev/null; do sleep 120; done
echo "[chain2] relation build done" >> $R/eval_agent_chain.log
# 3) 工具臂
$PY longbench_agent_eval.py --out longbench_agent_tools_results.json >> $R/v3_agent_tools.log 2>&1
date > $R/EVAL_AGENT_DONE
echo "[chain2] ALL DONE" >> $R/eval_agent_chain.log
