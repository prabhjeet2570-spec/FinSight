import type {Corpus,Health,QueryRequest,QueryResponse,Evaluation,Job} from '../types'
const base=import.meta.env.VITE_API_URL || ''
async function request<T>(path:string,init?:RequestInit):Promise<T>{
 const response=await fetch(base+path,init)
 if(!response.ok){const body=await response.json().catch(()=>({detail:'Unable to connect to the local API.'}));throw new Error(typeof body.detail==='string'?body.detail:'The request could not be completed.')}
 return response.json() as Promise<T>
}
export const api={
 corpus:()=>request<Corpus>('/api/corpus'),health:()=>request<Health>('/health'),history:()=>request<QueryResponse[]>('/api/history'),
 query:(payload:QueryRequest)=>request<QueryResponse>('/api/query',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)}),
 evaluation:()=>request<Evaluation>('/api/evaluation'),
 import:(data:FormData)=>request<Job>('/api/imports',{method:'POST',body:data}),
 job:(id:string)=>request<Job>('/api/imports/'+id),retry:(id:string)=>request<Job>('/api/imports/'+id+'/retry',{method:'POST'}),
}
