mod chess;
mod xiangqi;
mod search;

use std::time::Duration;

fn main() {
    let args: Vec<String> = std::env::args().collect();

    let mut game = "chess";
    let mut fen = String::new();
    let mut time_ms: u64 = 5000;

    let mut i = 1;
    while i < args.len() {
        match args[i].as_str() {
            "--game" => {
                i += 1;
                game = match args.get(i) {
                    Some(g) => g.as_str(),
                    None => {
                        eprintln!("Missing value for --game");
                        std::process::exit(1);
                    }
                };
            }
            "--fen" => {
                i += 1;
                fen = match args.get(i) {
                    Some(f) => f.clone(),
                    None => {
                        eprintln!("Missing value for --fen");
                        std::process::exit(1);
                    }
                };
            }
            "--time" => {
                i += 1;
                time_ms = match args.get(i).and_then(|t| t.parse().ok()) {
                    Some(t) => t,
                    None => {
                        eprintln!("Missing or invalid value for --time");
                        std::process::exit(1);
                    }
                };
            }
            _ => {
                eprintln!("Unknown argument: {}", args[i]);
                std::process::exit(1);
            }
        }
        i += 1;
    }

    let time_limit = Duration::from_millis(time_ms);

    match game {
        "chess" => {
            let fen = if fen.is_empty() {
                chess::board::STARTPOS.to_string()
            } else {
                fen
            };
            let board = chess::board::Board::from_fen(&fen);
            let best = search::iterative_deepening_chess(&board, time_limit);
            match best {
                Some(mv) => println!("{}", chess::moves::move_to_uci(mv)),
                None => {
                    eprintln!("No legal moves");
                    std::process::exit(1);
                }
            }
        }
        "xiangqi" => {
            let fen = if fen.is_empty() {
                xiangqi::board::STARTPOS.to_string()
            } else {
                fen
            };
            let board = xiangqi::board::Board::from_fen(&fen);
            let best = search::iterative_deepening_xiangqi(&board, time_limit);
            match best {
                Some(mv) => println!("{}", xiangqi::moves::move_to_coord(mv)),
                None => {
                    eprintln!("No legal moves");
                    std::process::exit(1);
                }
            }
        }
        _ => {
            eprintln!("Unknown game: {}. Use 'chess' or 'xiangqi'", game);
            std::process::exit(1);
        }
    }
}
