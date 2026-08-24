/** Giveaway / shill posts that non sono una storia vera. */
export function isNoisePost(text: string) {
  const value = text.toLowerCase();
  return (
    /airdrop|giveaway|give away/.test(value) ||
    /first \d+ people/.test(value) ||
    /drop your.{0,60}wallet/.test(value) ||
    /follow and (rt|retweet)/.test(value) ||
    /i['’]?m sending (total of )?\$/.test(value) ||
    /join my (private )?t(ele)?g/.test(value) ||
    /claim fee/.test(value)
  );
}
