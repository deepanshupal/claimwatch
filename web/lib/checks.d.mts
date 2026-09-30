export type Result = {platform:string;label:string;status:"unknown"|"taken"|"not_registered";detail:string;url?:string};
export const platforms: Record<string,string>;
export const tlds: string[];
export function parseName(input:string):string;
export function checkDomain(name:string,tld:string,fetcher?:typeof fetch):Promise<Result>;
export function checkProfile(platform:string,name:string,fetcher?:typeof fetch):Promise<Result>;
