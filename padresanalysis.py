import urllib.request
import json
import ssl
from collections import defaultdict, Counter
from datetime import datetime

# =====================================================================
# MODULE 1: PADRES SHUTDOWN FAILURES & PITCHER LEADERBOARD
# =====================================================================
def get_pitchers_in_inning(game_pk, inning_num, half):
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
    except Exception:
        return []

def run_padres_shutdown_failures(team_id=135, season=2026):
    schedule_url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}&season={season}&gameType=R&hydrate=linescore"
    
    print(f"\n[1] Fetching Padres Shutdown Failures for {season}...")
    try:
        context = ssl.create_default_context()
        req = urllib.request.Request(schedule_url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=context, timeout=10) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return

    failures = []
    pitcher_failures = Counter()
    total_padres_runs = 0
    total_allowed_runs = 0

    for date_info in data.get('dates', []):
        for game in date_info.get('games', []):
            if game.get('status', {}).get('detailedState') != 'Final':
                continue
                
            game_pk = game['gamePk']
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
                    
                    pitchers_in_inning = get_pitchers_in_inning(game_pk, inn_num, half)
                    for p in pitchers_in_inning:
                        pitcher_failures[p] += 1
                        
                    failures.append([
                        game_date, f"{away_team} @ {home_team}", 
                        str(padres_scored), str(runs_allowed), 
                        f"{half.title()} {inn_num}", ", ".join(pitchers_in_inning) or "Unknown"
                    ])

    diff = total_padres_runs - total_allowed_runs
    diff_str = f"+{diff}" if diff > 0 else str(diff)

    print("\n--- GOOGLE SHEETS EXPORT: GAME LOG ---")
    print("DATE\tMATCHUP\tPADRES RUNS SCORED\tRUNS ALLOWED\tINNING\tPITCHER(S)")
    for f in failures:
        print("\t".join(f))

    print("\n--- GOOGLE SHEETS EXPORT: SUMMARY ---")
    print("CATEGORY\tVALUE")
    print(f"Total Padres Runs Scored (in scoring innings)\t{total_padres_runs}")
    print(f"Total Runs Allowed (in immediate half-inning)\t{total_allowed_runs}")
    print(f"Net Run Differential\t{diff_str}")
    
    print("\n--- GOOGLE SHEETS EXPORT: PITCHER LEADERBOARD ---")
    print("SHUTDOWN FAILURES\tPITCHER")
    for pitcher, count in pitcher_failures.most_common():
        print(f"{count}\t{pitcher}")


# =====================================================================
# MODULE 2: LEAGUE-WIDE SHUTDOWN FAILURES BENCHMARK
# =====================================================================
def run_league_shutdowns(season=2026):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&season={season}&gameType=R&hydrate=linescore"
    
    print(f"\n[2] Fetching League-Wide Shutdown Failures for {season}...")
    try:
        context = ssl.create_default_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=context, timeout=20) as response:
            data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return

    team_names = {}
    scoring_opportunities = defaultdict(int)
    shutdown_failures = defaultdict(int)
    runs_scored_in_failures = defaultdict(int)
    runs_allowed_in_failures = defaultdict(int)
    games_played = defaultdict(int)

    for date_info in data.get('dates', []):
        for game in date_info.get('games', []):
            if game.get('status', {}).get('detailedState') != 'Final':
                continue

            away_id = game['teams']['away']['team']['id']
            away_name = game['teams']['away']['team']['name']
            home_id = game['teams']['home']['team']['id']
            home_name = game['teams']['home']['team']['name']

            team_names[away_id] = away_name
            team_names[home_id] = home_name

            games_played[away_id] += 1
            games_played[home_id] += 1

            innings = game.get('linescore', {}).get('innings', [])

            for idx, inning in enumerate(innings):
                away_runs = inning.get('away', {}).get('runs', 0)
                home_runs = inning.get('home', {}).get('runs', 0)

                if away_runs > 0:
                    scoring_opportunities[away_id] += 1
                    if home_runs > 0:
                        shutdown_failures[away_id] += 1
                        runs_scored_in_failures[away_id] += away_runs
                        runs_allowed_in_failures[away_id] += home_runs

                if home_runs > 0:
                    scoring_opportunities[home_id] += 1
                    if (idx + 1) < len(innings):
                        next_top_runs = innings[idx + 1].get('away', {}).get('runs', 0)
                        if next_top_runs > 0:
                            shutdown_failures[home_id] += 1
                            runs_scored_in_failures[home_id] += home_runs
                            runs_allowed_in_failures[home_id] += next_top_runs

    results = []
    for t_id, name in team_names.items():
        opps = scoring_opportunities[t_id]
        fails = shutdown_failures[t_id]
        gp = games_played[t_id]
        rate = round((fails / opps * 100) if opps > 0 else 0.0, 1)
        r_scored = runs_scored_in_failures[t_id]
        r_allowed = runs_allowed_in_failures[t_id]
        diff = r_scored - r_allowed
        
        diff_str = f"+{diff}" if diff > 0 else str(diff)
        results.append([name, gp, opps, fails, f"{rate}%", diff_str, rate])

    results.sort(key=lambda x: x[-1], reverse=True)

    print("\n--- GOOGLE SHEETS EXPORT: LEAGUE STANDINGS ---")
    print("RANK\tTEAM\tGP\tSCORING INN\tFAILURES\tFAILURE %\tDIFF")
    for rank, r in enumerate(results, 1):
        print(f"{rank}\t{r[0]}\t{r[1]}\t{r[2]}\t{r[3]}\t{r[4]}\t{r[5]}")


# =====================================================================
# MODULE 3: PADRES RELIEVER WORKLOAD & FATIGUE
# =====================================================================
def run_padres_bullpen_fatigue(team_id=135, season=2026):
    url = f"https://statsapi.mlb.com/api/v1/schedule?sportId=1&teamId={team_id}&season={season}&gameType=R&hydrate=linescore"
    
    print(f"\n[3] Fetching Reliever Fatigue/Workload for {season}...")
    try:
        context = ssl.create_default_context()
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req, context=context, timeout=15) as response:
            schedule_data = json.loads(response.read().decode('utf-8'))
    except Exception as e:
        print(f"❌ Connection error: {e}")
        return

    pitcher_appearances = defaultdict(list)

    for date_info in schedule_data.get('dates', []):
        for game in date_info.get('games', []):
            if game.get('status', {}).get('detailedState') != 'Final':
                continue
                
            game_pk = game['gamePk']
            game_date_str = game.get('gameDate', '')[:10]
            game_date = datetime.strptime(game_date_str, "%Y-%m-%d")

            box_url = f"https://statsapi.mlb.com/api/v1/game/{game_pk}/boxscore"
            try:
                req_box = urllib.request.Request(box_url, headers={'User-Agent': 'Mozilla/5.0'})
                with urllib.request.urlopen(req_box, context=context, timeout=10) as resp_box:
                    box_data = json.loads(resp_box.read().decode('utf-8'))
                    
                    teams = box_data.get('teams', {})
                    if teams.get('home', {}).get('team', {}).get('id') == team_id:
                        padres_pitchers = teams['home'].get('pitchers', [])
                        players = teams['home'].get('players', {})
                    else:
                        padres_pitchers = teams['away'].get('pitchers', [])
                        players = teams['away'].get('players', {})

                    for pid in padres_pitchers:
                        p_key = f"ID{pid}"
                        p_info = players.get(p_key, {})
                        p_name = p_info.get('person', {}).get('fullName', 'Unknown')
                        stats = p_info.get('stats', {}).get('pitching', {})
                        
                        pitches = stats.get('numberOfPitches', 0)
                        if pitches > 0:
                            pitcher_appearances[p_name].append({
                                'date': game_date,
                                'pitches': pitches
                            })
            except Exception:
                continue

    results = []
    for pitcher, logs in pitcher_appearances.items():
        avg_pitches = sum(l['pitches'] for l in logs) / len(logs) if logs else 0
        if avg_pitches > 55:
            continue  # Skip primary starting pitchers

        three_in_three_count = 0
        heavy_two_day_count = 0

        logs.sort(key=lambda x: x['date'])

        for i in range(len(logs)):
            current_date = logs[i]['date']
            recent_3_days = [l for l in logs if 0 <= (current_date - l['date']).days <= 2]
            if len(recent_3_days) >= 3:
                three_in_three_count += 1

            recent_2_days = [l for l in logs if 0 <= (current_date - l['date']).days <= 1]
            total_2d_pitches = sum(l['pitches'] for l in recent_2_days)
            if len(recent_2_days) == 2 and total_2d_pitches >= 40:
                heavy_two_day_count += 1
                
        results.append([pitcher, str(len(logs)), str(three_in_three_count), str(heavy_two_day_count)])

    results.sort(key=lambda x: int(x[1]), reverse=True)

    print("\n--- GOOGLE SHEETS EXPORT: RELIEVER WORKLOAD ---")
    print("PITCHER\tTOTAL OUTINGS\t3-IN-3 DAYS\t40+ PITCHES / 2 DAYS")
    for r in results:
        print("\t".join(r))


# =====================================================================
# MAIN MENU INTERFACE
# =====================================================================
def main():
    while True:
        print("\n" + "="*50)
        print("⚾ PADRES ANALYTICS SUITE ⚾")
        print("="*50)
        print("1. Padres Shutdown Failures & Pitcher Leaderboard")
        print("2. League-Wide Shutdown Failures Benchmark")
        print("3. Padres Reliever Fatigue & Workload Tracker")
        print("4. Run ALL Scripts")
        print("5. Exit")
        
        choice = input("\nEnter the number of the script to run (1-5): ").strip()
        
        if choice == '1':
            run_padres_shutdown_failures()
        elif choice == '2':
            run_league_shutdowns()
        elif choice == '3':
            run_padres_bullpen_fatigue()
        elif choice == '4':
            run_padres_shutdown_failures()
            run_league_shutdowns()
            run_padres_bullpen_fatigue()
        elif choice == '5':
            print("\nExiting script. Go Padres!")
            break
        else:
            print("\nInvalid choice. Please enter a number from 1 to 5.")

if __name__ == "__main__":
    main()