import urllib.request
import json
import ssl
from collections import Counter

def get_pitchers_in_inning(game_pk, inning_num, half):
    """Fetches the play-by-play data for a specific game and extracts the pitcher(s) for a given half-inning."""
    url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/playByPlay"
    try:
        context = ssl.create_default_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            pbp_data = json.loads(response.read().decode('utf-8'))
            
        pitchers = []
        for play in pbp_data.get('allPlays', []):
            about = play.get('about', {})
            if about.get('inning') == inning_num and about.get('halfInning') == half:
                pitcher_name = play.get('matchup', {}).get('pitcher', {}).get('fullName')
                if pitcher_name and pitcher_name not in pitchers:
                    pitchers.append(pitcher_name)
        return pitchers
    except Exception as e:
        return []

def find_shutdown_failures(team_id=135, season=2026):
    schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}&season={season}&gameType=R&hydrate=linescore"
    
    print("Fetching schedule and linescores from MLB API...")
    try:
        context = ssl.create_default_context()
        req = urllib.request.Request(schedule_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"❌ Connection or API error: {e}")
        return

    failures = []
    games_analyzed = 0
    pitcher_failures = Counter()
    total_padres_runs = 0
    total_allowed_runs = 0

    for date_info in data.get('dates', []):
        for game in date_info.get('games', []):
            if game.get('status', {}).get('detailedState') != 'Final':
                continue
                
            game_pk = game['gamePk']
            games_analyzed += 1
            game_date = game.get('gameDate', '')[:10]
            away_team = game['teams']['away']['team']['name']
            home_team = game['teams']['home']['team']['name']
            is_home = game['teams']['home']['team']['id'] == team_id

            innings = game.get('linescore', {}).get('innings', [])

            for idx, inning in enumerate(innings):
                inning_num = inning.get('num', idx + 1)
                away_runs = inning.get('away', {}).get('runs', 0)
                home_runs = inning.get('home', {}).get('runs', 0)

                failure_half_inning = None
                padres_scored = 0
                runs_allowed = 0

                if is_home:
                    if home_runs > 0 and (idx + 1) < len(innings):
                        next_top_runs = innings[idx + 1].get('away', {}).get('runs', 0)
                        if next_top_runs > 0:
                            padres_scored = home_runs
                            runs_allowed = next_top_runs
                            failure_half_inning = ('top', inning_num + 1)
                else:
                    if away_runs > 0 and home_runs > 0:
                        padres_scored = away_runs
                        runs_allowed = home_runs
                        failure_half_inning = ('bottom', inning_num)

                if failure_half_inning:
                    half, inn_num = failure_half_inning
                    total_padres_runs += padres_scored
                    total_allowed_runs += runs_allowed
                    
                    # Fetch the pitcher(s) who pitched during this specific half-inning
                    pitchers_in_inning = get_pitchers_in_inning(game_pk, inn_num, half)
                    
                    # Tally the failure for each pitcher who appeared in that half-inning
                    for p in pitchers_in_inning:
                        pitcher_failures[p] += 1
                        
                    failures.append({
                        'date': game_date,
                        'matchup': f"{away_team} @ {home_team}",
                        'detail': f"Scored {padres_scored} ➔ Allowed {runs_allowed} in {half.title()} {inn_num}",
                        'pitchers': ", ".join(pitchers_in_inning) or "Unknown"
                    })

    diff = total_padres_runs - total_allowed_runs
    diff_str = f"+{diff}" if diff > 0 else str(diff)

    print(f"\n✅ Analyzed {games_analyzed} completed games.")
    print(f"🚨 Found {len(failures)} shutdown inning failures:\n")
    
    for f in failures:
        print(f"[{f['date']}] {f['matchup']} | {f['detail']} | Pitcher(s): {f['pitchers']}")

    print("\n" + "="*55)
    print("📊 SHUTDOWN FAILURE TOTALS SUMMARY")
    print("="*55)
    print(f"Total Padres Runs Scored (in scoring innings):   {total_padres_runs}")
    print(f"Total Runs Allowed (in immediate half-inning):   {total_allowed_runs}")
    print(f"Net Run Differential:                            {diff_str}")
    
    print("\n" + "="*55)
    print("📉 PITCHERS WITH MOST SHUTDOWN FAILURES")
    print("="*55)
    
    if not pitcher_failures:
        print("No pitcher data found.")
    else:
        # Sort and print pitchers by most failures
        for pitcher, count in pitcher_failures.most_common():
            print(f"{count} - {pitcher}")
    print("="*55)

if __name__ == "__main__":
    find_shutdown_failures()