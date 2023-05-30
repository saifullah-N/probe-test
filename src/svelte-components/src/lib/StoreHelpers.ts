import { get, type Writable } from "svelte/store";

export function waitForChange<T>(writable: Writable<T>): Promise<T> {
  let unsubscribe:()=>{};
  const promise = new Promise(resolve => {
    let receivedInitial = false;
    let previousValue : any;
    unsubscribe = writable.subscribe(value => {
      if (!receivedInitial) {
        receivedInitial = true;
        previousValue = value;
      } else if (value !== previousValue) {
        resolve(value);
      }
    });
  });
  promise.then(unsubscribe);
  return promise;
}
// export function listenForChange<T>(writable: Writable<T>, cb: (value: T) => void) {
//     const priorValue = get(writable);

//     const unsubscribe = writable.subscribe((value) => {
//         console.log({value , priorValue}, typeof(value))

//         if (value !== priorValue) {
//             console.log("inside if " , {value ,  priorValue});
            
//             unsubscribe();
//         if (! this.callbackCalled) {
//             this.callbackCalled = true;
//             cb(value);
//     }
//         }
//     });
// }

// export function waitForChange<T>(name:string,writable: Writable<T>): Promise<T> {
//     console.log("waiting for change: ",get(writable) ,name);

//     return new Promise((resolve) => {
//         console.log('23 before resolve',name);
        
//         listenForChange(writable, (value) => resolve(value)); 
//     });
// }
//https://stackoverflow.com/questions/64862161/svelte-store-function-update?rq=1
//https://stackoverflow.com/questions/64862161/svelte-store-function-update?rq=


// export function waitForChange<T>(writable: Writable<T>): Promise<T> {
//         const priorValue = get(writable);
//         let newValue : Boolean = false 
//         let unsubscribe : ()=>{}
//         while( newValue !== priorValue){
//             unsubscribe = writable.subscribe((value) => {newValue = value})
//             unsubscribe()
//         }
        
//     return new Promise((resolve) => {
//         resolve(newValue)
//     });
// }

