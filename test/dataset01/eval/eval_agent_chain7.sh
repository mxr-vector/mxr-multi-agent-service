#!/usr/bin/env bash
# 构建已完成，仅跑工具臂收敛（600 条 ok）→ 标记
R=/home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/results
PY=/home/yuanjie/mydata/selfspace/multi-agent-service/.venv/bin/python
cd /home/yuanjie/mydata/selfspace/multi-agent-service/test/dataset01/eval
for i in 1 2 3 4 5 6; do
    $PY longbench_agent_eval.py --out longbench_agent_tools_results.json >> $R/v3_agent_tools.log 2>&1
    N=$(wc -l < $R/longbench_agent_tools_results.json.partial.jsonl 2>/dev/null || echo 0)
    echo "[chain7] tools pass $i: ok=$N" >> $R/eval_agent_chain.log
    [ "$N" -ge 600 ] && break
    sleep 60
done
date > $R/EVAL_AGENT_DONE
echo "[chain7] ALL DONE" >> $R/eval_agent_chain.log
