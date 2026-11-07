import {hostSummaryText} from './host-dashboard-summary.js';

/** A cached row is a recheck intent, never an observation or input lease. */
export function blockedTargetList({store,host,onOpen,disabled=false}) {
  const section=document.createElement('section');section.className='blocked-target-list';section.setAttribute('aria-label','受阻窗格清单');
  const record=store.get(host),wasCurrent=record?.current,note=document.createElement('p');
  const fresh=wasCurrent && record.phase==='fresh';
  if(!record)note.textContent='受阻窗格未知；请先连接并核验会话快照。';
  else if(wasCurrent && !fresh)note.textContent=record.blocked.length ? '上次快照包含受阻窗格，持续更新不可用。请选择原目标重新核查。' : '上次快照没有可定位的受阻窗格，持续更新不可用。';
  else if(!record.blocked.length)note.textContent=record.current ? (record.unknown?'已核验受阻清单为空；仍有状态未知的窗格。':'已核验受阻清单为空。') : '上次清单为空（已陈旧）；当前受阻情况未知。';
  else note.textContent=record.current?'选择一个受阻窗格；新观察会重新核查原主机、会话与目标。':'上次受阻清单（已陈旧）；只能显式重新核查原目标。';
  section.append(note);
  for(const target of record?.blocked || []) {
    const button=document.createElement('button');button.type='button';button.dataset.blockedTarget=`${target.paneId}/${target.terminalId}`;
    button.textContent=`${fresh?'观察受阻目标':'重新核查此目标'} · ${target.paneId} · ${target.terminalId}${target.label?` · ${target.label}`:''}`;
    button.disabled=disabled;button.onclick=()=>{if(!button.disabled && record.current===wasCurrent && store.blockedTarget(host,target))onOpen(target);};section.append(button);
  }
  section.title=hostSummaryText(record);return section;
}
