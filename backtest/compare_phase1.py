# -*- coding: utf-8 -*-
import sys
import pandas as pd
import numpy as np

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

f_old = 'signals_modified_m12_s5.csv'
f_new = 'signals_phase1_m12_s5.csv'

df_old = pd.read_csv(f_old)
df_new = pd.read_csv(f_new)

print('=' * 80)
print('         核心策略修改前後歷史回測數據完整對比 (9 檔標的，2020-2026)')
print('=' * 80)

def get_stats(df):
    res = {}
    n_total = len(df)
    bench_r20 = df['ret_t1_20'].mean() * 100
    bench_w20 = (df['ret_t1_20'] > 0).mean() * 100
    bench_r60 = df['ret_t1_60'].mean() * 100
    bench_w60 = (df['ret_t1_60'] > 0).mean() * 100
    res['bench'] = (n_total, bench_r20, bench_w20, bench_r60, bench_w60)

    for act in ['BUY', 'HOLD', 'WAIT', 'SELL']:
        sub = df[df['action'] == act]
        n = len(sub)
        if n == 0:
            res[act] = (0, 0, 0, 0, 0, 0, 0)
            continue
        r20 = sub['ret_t1_20'].mean() * 100
        ex20 = r20 - bench_r20
        w20 = (sub['ret_t1_20'] > 0).mean() * 100
        r60 = sub['ret_t1_60'].mean() * 100
        ex60 = r60 - bench_r60
        w60 = (sub['ret_t1_60'] > 0).mean() * 100
        res[act] = (n, r20, ex20, w20, r60, ex60, w60)
    return res

s_old = get_stats(df_old)
s_new = get_stats(df_new)

print('\n【1. 決策分布與筆數變化】')
print(f'總樣本數: {len(df_old)} 筆')
for act in ['BUY', 'HOLD', 'WAIT', 'SELL']:
    n_old = s_old[act][0]
    n_new = s_new[act][0]
    diff = n_new - n_old
    pct_old = n_old / len(df_old) * 100
    pct_new = n_new / len(df_new) * 100
    print(f'  {act:<5}: 修改前 {n_old:>4} 筆 ({pct_old:5.1f}%) -> 修改後 {n_new:>4} 筆 ({pct_new:5.1f}%) [差額 {diff:+4d} 筆]')

print('\n【2. 20 交易日 績效與勝率對比 (T+1 開盤進場)】')
print(f'  基準全樣本 (全體平均): 20日均報酬 {s_old["bench"][1]:+.2f}%, 勝率 {s_old["bench"][2]:.1f}%')
print('  ' + '-' * 76)
print('  決策   修改前 20日報酬 (勝率)      修改後 20日報酬 (勝率)       超額變化     勝率增益')
print('  ' + '-' * 76)
for act in ['BUY', 'HOLD', 'WAIT', 'SELL']:
    o = s_old[act]
    n = s_new[act]
    d_ex20 = n[2] - o[2]
    d_w20 = n[3] - o[3]
    print(f'  {act:<5}  {o[1]:+6.2f}% (勝率 {o[3]:5.1f}%)   ->  {n[1]:+6.2f}% (勝率 {n[3]:5.1f}%)    超額 {d_ex20:+5.2f}%   勝率 {d_w20:+5.1f} pp')

print('\n【3. 60 交易日 核心優勢週期績效與勝率對比 (T+1 開盤進場)】')
print(f'  基準全樣本 (全體平均): 60日均報酬 {s_old["bench"][3]:+.2f}%, 勝率 {s_old["bench"][4]:.1f}%')
print('  ' + '-' * 76)
print('  決策   修改前 60日報酬 (勝率)      修改後 60日報酬 (勝率)       超額變化     勝率增益')
print('  ' + '-' * 76)
for act in ['BUY', 'HOLD', 'WAIT', 'SELL']:
    o = s_old[act]
    n = s_new[act]
    d_ex60 = n[5] - o[5]
    d_w60 = n[6] - o[6]
    print(f'  {act:<5}  {o[4]:+6.2f}% (勝率 {o[6]:5.1f}%)   ->  {n[4]:+6.2f}% (勝率 {n[6]:5.1f}%)    超額 {d_ex60:+5.2f}%   勝率 {d_w60:+5.1f} pp')

print('\n【4. 看多訊號 (BUY + HOLD) 整體方向品質】')
sub_long_old = df_old[df_old['action'].isin(['BUY', 'HOLD'])]
sub_long_new = df_new[df_new['action'].isin(['BUY', 'HOLD'])]

w20_l_old = (sub_long_old['ret_t1_20'] > 0).mean() * 100
w20_l_new = (sub_long_new['ret_t1_20'] > 0).mean() * 100
r20_l_old = sub_long_old['ret_t1_20'].mean() * 100
r20_l_new = sub_long_new['ret_t1_20'].mean() * 100

w60_l_old = (sub_long_old['ret_t1_60'] > 0).mean() * 100
w60_l_new = (sub_long_new['ret_t1_60'] > 0).mean() * 100
r60_l_old = sub_long_old['ret_t1_60'].mean() * 100
r60_l_new = sub_long_new['ret_t1_60'].mean() * 100

print(f'  看多訊號總數: 修改前 {len(sub_long_old)} 筆 -> 修改後 {len(sub_long_new)} 筆 (減少 {len(sub_long_old)-len(sub_long_new)} 筆無效訊號)')
print(f'  20 日看多勝率: {w20_l_old:.1f}% -> {w20_l_new:.1f}% ({w20_l_new - w20_l_old:+.1f} pp) ｜ 均報酬: {r20_l_old:+.2f}% -> {r20_l_new:+.2f}% ({r20_l_new - r20_l_old:+.2f}%)')
print(f'  60 日看多勝率: {w60_l_old:.1f}% -> {w60_l_new:.1f}% ({w60_l_new - w60_l_old:+.1f} pp) ｜ 均報酬: {r60_l_old:+.2f}% -> {r60_l_new:+.2f}% ({r60_l_new - r60_l_old:+.2f}%)')

print('\n【5. 9 檔個股個別勝率差異 (BUY 訊號 20日與60日勝率)】')
print('  ' + '-' * 76)
print('  代號   修改前 20日勝率 (筆數)    修改後 20日勝率 (筆數)     修改前 60日勝率    修改後 60日勝率')
print('  ' + '-' * 76)
for tk in sorted(df_old['ticker'].unique()):
    t_old = df_old[(df_old['ticker'] == tk) & (df_old['action'] == 'BUY')]
    t_new = df_new[(df_new['ticker'] == tk) & (df_new['action'] == 'BUY')]
    w20_o = (t_old['ret_t1_20'] > 0).mean() * 100 if len(t_old) else 0.0
    w20_n = (t_new['ret_t1_20'] > 0).mean() * 100 if len(t_new) else 0.0
    w60_o = (t_old['ret_t1_60'] > 0).mean() * 100 if len(t_old) else 0.0
    w60_n = (t_new['ret_t1_60'] > 0).mean() * 100 if len(t_new) else 0.0
    print(f'  {tk:<5}  {w20_o:5.1f}% (n={len(t_old):<3})        ->  {w20_n:5.1f}% (n={len(t_new):<3})          {w60_o:5.1f}%           {w60_n:5.1f}% ({w60_n-w60_o:+.1f} pp)')



