import type {QueryResponse,Source} from '../types'
import {Icon} from './Icon'
export function EvidencePanel({result,selected,onSelect}:{result:QueryResponse;selected:Source|null;onSelect:(s:Source|null)=>void}){
 if(selected)return <aside className="evidence-panel inspector" aria-label="Source inspector">
  <div className="panel-title"><span>Source inspector</span><button className="icon-button" onClick={()=>onSelect(null)} aria-label="Close source inspector"><Icon name="close"/></button></div>
  <div className="source-heading"><span className={`company-badge ${selected.ticker.toLowerCase()}`}>{selected.ticker}</span><span>{selected.form} · {selected.type==='fact'?'Structured fact':'Source passage'}</span></div>
  <h3>{selected.type==='fact'?selected.concept?.split(':')[1]:selected.section}</h3>
  <div className="source-quote">{selected.text}</div>
  <dl className="source-metadata"><dt>Company</dt><dd>{selected.company}</dd><dt>Accession</dt><dd>{selected.accession}</dd><dt>Period end</dt><dd>{selected.period_end}</dd>{selected.period_start&&<><dt>Period start</dt><dd>{selected.period_start}</dd></>}{selected.unit&&<><dt>Unit</dt><dd>{selected.unit}</dd><dt>Reported value</dt><dd>{Number(selected.value).toLocaleString('en-US')}</dd><dt>XBRL precision</dt><dd>{selected.decimals}</dd><dt>Context</dt><dd>{selected.context_id}</dd></>}</dl>
  <a className="source-link" href={selected.source_url} target="_blank" rel="noreferrer"><Icon name="link"/> Open original SEC filing <Icon name="arrow" size={14}/></a>
  <p className="subtle small">Source passages are normalized from the filing HTML. Section and character positions are retained; page numbers are not invented.</p>
 </aside>
 return <aside className="evidence-panel" aria-label="Retrieved evidence"><div className="panel-title"><span>Evidence</span><span className="count">{result.sources.length}</span></div>
  <p className="subtle small evidence-intro">Every reference opens the exact passage or XBRL fact behind it.</p>
  {result.sources.map((source,i)=><button className="source-card" key={source.id} onClick={()=>onSelect(source)}><div className="source-top"><span className="source-number">{i+1}</span><span className={`company-badge ${source.ticker.toLowerCase()}`}>{source.ticker}</span><span className="small subtle">{source.form}</span><Icon name="chevron" size={14}/></div><strong>{source.type==='fact'?source.concept?.split(':')[1].replace(/([a-z])([A-Z])/g,'$1 $2'):source.section}</strong><p>{source.text.slice(0,160)}{source.text.length>160?'…':''}</p><span className="small subtle">{source.type==='fact'?'Inline XBRL · '+source.unit:'Passage '+((source.ordinal??0)+1)}</span></button>)}
  {!result.sources.length&&<div className="empty-evidence"><Icon name="file" size={30}/><p>No supporting sources</p><span className="small subtle">Expand the corpus or change the question.</span></div>}
 </aside>
}
