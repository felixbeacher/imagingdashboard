"""Regenerate risk.svg from the supplied scored CSV; requires matplotlib.
No recalibration or new observations are inferred. Run after updating the CSV.
"""
from pathlib import Path
import csv
import hashlib
from datetime import datetime
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
import matplotlib.dates as mdates

ROOT=Path(__file__).resolve().parent
rows=list(csv.DictReader((ROOT/'risk-data.csv').open()))
names=['Geopolitical tension','Financial stress','Supply-chain pressure','Energy price pressure','Food price pressure']
dates=[datetime.fromisoformat(r['month']) for r in rows]
scores=[[float(r[name+' | score_0_100']) for r in rows] for name in names]
totals=[float(r['Global risk composite | 0_100']) for r in rows]
colors=['#67c8ef','#ac9bff','#63d8ba','#f3b56a','#e587a5']
plt.rcParams.update({'font.family':'DejaVu Sans','text.color':'#e8eef7','axes.labelcolor':'#acbbce','xtick.color':'#acbbce','ytick.color':'#acbbce','svg.fonttype':'none'})
fig,axes=plt.subplots(6,1,figsize=(14,13),sharex=True,gridspec_kw={'height_ratios':[2.4,1,1,1,1,1]})
fig.patch.set_facecolor('#101a28')
for ax in axes:
 ax.set_facecolor('#101a28');ax.set_ylim(0,105);ax.set_yticks([0,50,100]);ax.grid(axis='y',color='#34445b',alpha=.5,linewidth=.6)
 for spine in ax.spines.values():spine.set_visible(False)
 ax.tick_params(length=0,labelsize=9);ax.set_xlim(dates[0],dates[-1])
axes[0].stackplot(dates,[[v/5 for v in ss] for ss in scores],colors=colors,alpha=.65)
axes[0].plot(dates,totals,color='#ffffff',lw=2.2)
axes[0].set_title('GLOBAL PRESSURE COMPOSITE',loc='left',fontsize=14,fontweight='bold',pad=18)
peak=max(range(len(totals)),key=totals.__getitem__)
axes[0].annotate(f'Peak {totals[peak]:.1f}\n{dates[peak]:%b %Y}',xy=(dates[peak],totals[peak]),xytext=(dates[peak],55),fontsize=10,ha='center',arrowprops={'arrowstyle':'-','color':'#e8eef7'})
axes[0].text(.995,.89,f'{dates[-1]:%b %Y}  {totals[-1]:.1f}',transform=axes[0].transAxes,ha='right',fontsize=11,color='white',bbox={'facecolor':'#101a28','edgecolor':'none','alpha':.8})
for ax,name,color,ss in zip(axes[1:],names,colors,scores):
 ax.plot(dates,ss,color=color,lw=1.8);ax.fill_between(dates,ss,color=color,alpha=.10);ax.set_title(name.upper(),loc='left',fontsize=10,pad=8,fontweight='bold');ax.text(.995,.84,f'{ss[-1]:.1f}',transform=ax.transAxes,ha='right',color=color,fontsize=10)
axes[-1].xaxis.set_major_locator(mdates.YearLocator());axes[-1].xaxis.set_major_formatter(mdates.DateFormatter('%Y'))
fig.subplots_adjust(left=.055,right=.975,top=.91,bottom=.255,hspace=.60)
# Event labels use the same time scale as the component plots. Three lanes
# keep adjacent events readable without treating event timing as causality.
events = [
 ('2020-03-11', 'COVID-19 pandemic', 0),
 ('2021-12-01', 'Supply-chain peak', 0),
 ('2022-02-24', 'Russia invades Ukraine', 1),
 ('2023-03-10', 'Banking turmoil', 0),
 ('2023-10-07', 'Israel–Gaza war', 1),
 ('2024-01-01', 'Red Sea disruption', 2),
 ('2025-04-02', 'US tariff shock', 0),
 ('2025-06-13', 'Israel–Iran escalation', 1),
 ('2026-02-28', 'Iran escalation', 0),
]
timeline=fig.add_axes([.055,.075,.92,.13])
timeline.set_xlim(dates[0],dates[-1]);timeline.set_ylim(0,1);timeline.axis('off')
timeline.axhline(.94,color='#64748b',lw=.8)
for when,label,lane in events:
 day=datetime.fromisoformat(when)
 if not dates[0] <= day <= dates[-1]: continue
 for ax in axes:ax.axvline(day,color='#acbbce',alpha=.18,lw=.65,ls=':')
 y=[.64,.32,.02][lane]
 timeline.plot([day,day],[.94,y+.12],color='#64748b',lw=.7)
 timeline.plot(day,.94,'o',color='#d7e2ef',markersize=3)
 align='left' if day.year==2020 else 'center'
 timeline.text(day,y,f'{day:%b %Y}\n{label}',ha=align,va='center',fontsize=8.5,color='#d7e2ef')
fig.text(.055,.218,'MAJOR EVENTS · Dates provide context, not proof of causation',fontsize=9,color='#acbbce')
fig.text(.055,.967,'JAN 2020 – SEP 2026  ·  Five components  ·  Monthly observations',fontsize=11,color='#acbbce')
fig.text(.055,.038,'Composite = mean of five historical percentile scores (fixed Jan 2000–Dec 2025 reference). Not a crisis probability.',fontsize=9,color='#acbbce')
fig.text(.055,.019,'Sources: Caldara & Iacoviello · US Treasury OFR · New York Fed · World Bank. Chart regenerated from supplied risk-data.csv.',fontsize=8.5,color='#acbbce')
fig.savefig(ROOT/'risk.svg',facecolor=fig.get_facecolor(),metadata={'Title':'Global pressure composite — five components, January 2020 to September 2026'})
digest=hashlib.sha256((ROOT/'risk-data.csv').read_bytes()).hexdigest();p=ROOT/'risk.svg';p.write_text(p.read_text().replace('<svg ',f'<!-- risk-data-sha256:{digest} -->\n<svg ',1))
fig.savefig(ROOT/'global-risk-preview.png',dpi=110,facecolor=fig.get_facecolor())
