import {api} from './client.js';
export const datasets={list:()=>api('/datasets'),get:id=>api('/datasets/'+id),create:data=>api('/datasets',{method:'POST',body:JSON.stringify(data)})};
export const jobs={list:()=>api('/jobs'),get:id=>api('/jobs/'+id),create:data=>api('/jobs',{method:'POST',body:JSON.stringify(data)}),approve:id=>api('/jobs/'+id+'/approve',{method:'POST'})};
export const reports={list:()=>api('/reports'),create:data=>api('/reports',{method:'POST',body:JSON.stringify(data)}),toggle:id=>api('/reports/'+id+'/toggle',{method:'POST'}),deliveries:()=>api('/deliveries')};
export const retests={
 batches:()=>api('/retests/batches'),
 createBatch:data=>api('/retests/batches',{method:'POST',body:JSON.stringify(data)}),
 trial:data=>api('/retests/trial',{method:'POST',body:JSON.stringify(data)}),
 issue:data=>api('/retests/issue',{method:'POST',body:JSON.stringify(data)}),
 vouchers:status=>api('/retests/vouchers'+(status?('?status='+status):'')),
};
