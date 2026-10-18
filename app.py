            p2.metric("Estimated position", f"{plan['lots']:.4f} lots")
            p3.metric("Planned risk", f"${plan['risk_usd']:.2f}")

            st.write(
                f"Estimated target reward at this plan: **${plan.get('planned_reward_usd', 0):.2f}** "
                f"before spreads, commissions, slippage, swaps, and contract differences."
            )
            st.caption(
                f"Approximate units: {plan['units']:,.0f}. Confirm minimum lot size, lot step, pip value, "
                "and contract size with your broker before using these figures even in a demo account."
            )
        else:
            st.write(
                f"Paper account: **${balance:.2f}** · risk setting: **{risk_pct:.1f}%** "
                f"· maximum planned risk per trade: **${plan['risk_usd']:.2f}**."
            )

        st.subheader("Candlestick chart and estimated zones")
        fig = go.Figure()
        fig.add_trace(go.Candlestick(
            x=candles["datetime"],
            open=candles["open"],
            high=candles["high"],
            low=candles["low"],
            close=candles["close"],
            name=symbol,
        ))
        fig.add_trace(go.Scatter(
            x=candles["datetime"], y=candles["ema20"],
            mode="lines", name="EMA 20",
        ))
        fig.add_trace(go.Scatter(
            x=candles["datetime"], y=candles["ema50"],
            mode="lines", name="EMA 50",
        ))

        x_start = candles["datetime"].iloc[0]
        x_end = candles["datetime"].iloc[-1]
        for zone in plan["demands"]:
            fig.add_shape(
                type="rect", xref="x", yref="y",
                x0=x_start, x1=x_end, y0=zone["low"], y1=zone["high"],
                fillcolor="rgba(0, 180, 100, 0.10)", line=dict(width=0),
                layer="below",
            )
        for zone in plan["supplies"]:
            fig.add_shape(
                type="rect", xref="x", yref="y",
                x0=x_start, x1=x_end, y0=zone["low"], y1=zone["high"],
                fillcolor="rgba(220, 60, 60, 0.10)", line=dict(width=0),
                layer="below",
            )
        if decision in ("BUY", "SELL"):
            fig.add_hline(y=plan["entry"], line_dash="dot", annotation_text="Entry")
            fig.add_hline(y=plan["stop"], line_dash="dash", annotation_text="Stop-loss")
            fig.add_hline(y=plan["target"], line_dash="dash", annotation_text="Take-profit")

        fig.update_layout(
            height=650,
            xaxis_rangeslider_visible=False,
            margin=dict(l=10, r=10, t=30, b=10),
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0),
        )
        st.plotly_chart(fig, use_container_width=True)

        zone_col1, zone_col2 = st.columns(2)
        with zone_col1:
            st.markdown("**Estimated demand zones**")
            if plan["demands"]:
                st.dataframe(pd.DataFrame([
                    {"Zone low": format_price(z["low"], symbol),
                     "Zone high": format_price(z["high"], symbol)}
                    for z in plan["demands"]
                ]), use_container_width=True, hide_index=True)
            else:
                st.write("No demand zones detected in this candle sample.")
        with zone_col2:
            st.markdown("**Estimated supply zones**")
            if plan["supplies"]:
                st.dataframe(pd.DataFrame([
                    {"Zone low": format_price(z["low"], symbol),
                     "Zone high": format_price(z["high"], symbol)}
                    for z in plan["supplies"]
                ]), use_container_width=True, hide_index=True)
            else:
                st.write("No supply zones detected in this candle sample.")

        with st.expander("View latest candles and indicators"):
            show_cols = ["datetime", "open", "high", "low", "close", "ema20", "ema50", "rsi14", "atr14"]
            st.dataframe(candles[show_cols].tail(30).sort_values("datetime", ascending=False),
                         use_container_width=True, hide_index=True)

        st.caption(
            "Method note: zones use recent local swing highs/lows with an ATR-based width. "
            "A BUY/SELL candidate requires trend alignment, RSI confirmation, and price near a zone. "
            "This simple model is not backtested or validated and may produce false signals. "
            "A 1:2 planned reward/risk is a target calculation, not a promise of outcome."
        )

    except requests.exceptions.Timeout:
        st.error("Twelve Data took too long to respond. Please try again.")
    except requests.exceptions.HTTPError as exc:
        st.error(f"HTTP error while requesting market data: {exc}")
    except requests.exceptions.RequestException as exc:
        st.error(f"Could not connect to Twelve Data: {exc}")
    except ValueError as exc:
        st.error(str(exc))
    except Exception as exc:
        st.error(f"Unexpected app error: {exc}")

else:
    st.info("Choose an instrument and timeframe, then click **Analyze market** to load candles and generate a rule-based paper-trading analysis.")

st.divider()
st.caption("Forex AI Analyst • Educational paper-trading prototype • No real-money order execution")
